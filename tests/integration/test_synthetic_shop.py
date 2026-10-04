import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from dlens.ingest import IngestResult, ingest
from dlens.ingest.runner import find_dbt
from dlens.lineage import ParseQuality, compare, extract_lineage, short_id

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parents[2] / "corpora" / "synthetic_shop"
V1_MODELS = {
    Path(line.split()[1]).stem for line in (CORPUS / "v1_frozen.sha256").read_text().splitlines()
}


def _spec_columns() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(models, seeds) -> column names, from the gold spec's inventory (`models:` and `seeds:`)."""
    spec = yaml.safe_load((CORPUS / "lineage_spec.yml").read_text())
    models = {name: set(m["columns"]) for name, m in spec["models"].items()}
    seeds = {name: set(cols) for name, cols in spec["seeds"].items()}
    return models, seeds


@pytest.fixture(scope="module")
def ingested(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, IngestResult]:
    project = tmp_path_factory.mktemp("ss") / "synthetic_shop"  # keep the repo free of target/
    shutil.copytree(CORPUS, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs"))
    return project, ingest(project)


def test_catalog_matches_gold_spec(ingested: tuple[Path, IngestResult]) -> None:
    spec_models, spec_seeds = _spec_columns()
    assert len(spec_models) == 49

    _, r = ingested
    assert r.unmapped == []
    assert {m.name for m in r.manifest.models} == set(spec_models)
    assert {s.name for s in r.manifest.seeds} == set(spec_seeds)

    built = {t.name: {c.name for c in t.columns} for t in r.catalog.tables}
    for name, expected in {**spec_models, **spec_seeds}.items():
        actual = built[name]
        assert not expected - actual, f"{name}: missing columns {sorted(expected - actual)}"
        assert not actual - expected, f"{name}: extra columns {sorted(actual - expected)}"


def test_dbt_tests_pass(tmp_path: Path) -> None:
    """`ingest` skips tests, so run a full build (seeds, models, tests) on real data."""
    project = tmp_path / "synthetic_shop"
    shutil.copytree(CORPUS, project)
    cmd = [str(find_dbt()), "build", "--project-dir", str(project), "--profiles-dir", str(project)]
    result = subprocess.run(cmd, cwd=project, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]


def test_lineage_matches_gold_spec(ingested: tuple[Path, IngestResult]) -> None:
    """Gate (spec §14, v0.1): direct-edge F1 >= 0.95 against the hand-written gold spec.

    The 15 frozen v1 models match the gold exactly. Every disagreement on a new model, and every
    model-level citation, is a known parser gap listed in engine_gaps.yml: the observed sets must
    equal the file, so a new gap fails and a fixed gap fails until its entry is removed."""
    project, r = ingested
    result = extract_lineage(r, project)
    assert all(p.quality == ParseQuality.FULL for p in result.parse_report.values())
    gold = yaml.safe_load((CORPUS / "lineage_spec.yml").read_text())["edges"]
    report = compare(result.edges, [g for g in gold if g["phase"] == "v0.1"])
    seen = (
        {(f, t, None, "extra", k) for f, t, k in report.extra}
        | {(f, t, k, "missing", None) for f, t, k in report.missing}
        | {(f, t, g, "wrong_kind", e) for f, t, g, e in report.kind_mismatches}
    )
    assert {d for d in seen if d[1].split(".")[0] in V1_MODELS} == set()

    gaps = yaml.safe_load((CORPUS / "engine_gaps.yml").read_text())
    known = {
        (g["from"], g["to"], g["gold_kind"], g["engine"], g.get("engine_kind"))
        for g in gaps["direct_edges"]
    }
    assert seen == known
    cited_by_model = {
        (short_id(e.from_column), short_id(e.to_column))
        for e in result.edges
        if e.model_level_citation
    }
    assert cited_by_model == {(g["from"], g["to"]) for g in gaps["model_level_citations"]}
    assert report.f1 >= 0.95 and report.kind_accuracy >= 0.95


def test_spec_depends_on_matches_dbt_ref_graph(ingested: tuple[Path, IngestResult]) -> None:
    """The gold's models.<m>.depends_on (DESIGN_v2 §2 "Upstream") equals dbt's ref graph."""
    _, r = ingested
    spec = yaml.safe_load((CORPUS / "lineage_spec.yml").read_text())["models"]
    name = {n.unique_id: n.name for n in [*r.manifest.models, *r.manifest.seeds]}
    dbt = {m.name: sorted(name[u] for u in m.depends_on.nodes) for m in r.manifest.models}
    assert dbt == {m: sorted(v["depends_on"]) for m, v in spec.items()}


def test_data_checks_are_dbt_tests_that_ingest_ignores(ingested: tuple[Path, IngestResult]) -> None:
    """The §7.2 data checks are singular tests: in dbt's manifest, never in the dlens graph."""
    project, r = ingested
    raw = json.loads((project / "target" / "manifest.json").read_text())["nodes"]
    singular = {n["name"] for n in raw.values() if n["resource_type"] == "test"}
    assert {"assert_no_constant_seed_columns", "assert_left_joins_have_unmatched"} <= singular
    assert {n.resource_type for n in r.manifest.nodes.values()} <= {"model", "seed", "source"}
    assert len(r.manifest.models) == 49


def test_indirect_edges_follow_d7_and_carry_their_clause(
    ingested: tuple[Path, IngestResult],
) -> None:
    """ADR 0020 invariants on the real corpus (the F1 gate against the gold is S04):
    no indirect (from, to) pair also has a direct edge, every edge has the clause text that
    contains its key column, and engine_gaps.yml records the model-level citation gap exactly
    while it exists."""
    project, r = ingested
    result = extract_lineage(r, project)
    assert result.indirect
    direct = {(e.from_column, e.to_column) for e in result.edges}
    assert not {(e.from_column, e.to_column) for e in result.indirect} & direct
    for e in result.indirect:
        assert e.expression.strip(), e
        assert e.key.split(".")[-1].lower() in e.expression.lower(), e
    gaps = yaml.safe_load((CORPUS / "engine_gaps.yml").read_text())
    listed = {g["gap"] for g in gaps["indirect_edges"]}
    citation_gap = "indirect-edge clause citations are model-level"
    assert (citation_gap in listed) == all(e.model_level_citation for e in result.indirect)
    assert listed <= {citation_gap}


def _key_is_cited(key: str, chunk: str) -> bool:
    token = key.replace('"', "").split(".")[-1]
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", chunk, re.IGNORECASE) is not None


@pytest.mark.xfail(
    strict=True, reason="S04: no clause locator yet; indirect citations are model-level"
)
def test_every_indirect_edge_cites_lines_that_hold_its_key(
    ingested: tuple[Path, IngestResult],
) -> None:
    """S04: each indirect edge cites its clause in the model's source file (the file and line
    numbering of direct edges), and the cited lines contain its key as written."""
    project, r = ingested
    result = extract_lineage(r, project)
    files = {e.to_column.rsplit(".", 1)[0]: e.file for e in result.edges}
    for e in result.indirect:
        assert not e.model_level_citation, e
        assert e.file == files[e.to_column.rsplit(".", 1)[0]], e
        lines = (project / e.file).read_text().splitlines()
        assert 1 <= e.lines[0] <= e.lines[1] <= len(lines), e
        chunk = "\n".join(lines[e.lines[0] - 1 : e.lines[1]])
        assert _key_is_cited(e.key, chunk), (e.key, e.file, e.lines)
    assert all(not p.citation_gaps for p in result.parse_report.values())
