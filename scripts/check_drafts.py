"""Checks for the test and set-E question drafts (S15a, docs/plans/s15a-drafts-design.md §4).

uv run python scripts/check_drafts.py                 # both v1 drafts; exit 1 on any failure
uv run python scripts/check_drafts.py --allow-short   # counts below the table are reported, not failed
uv run python scripts/check_drafts.py --test PATH --external PATH

Reads only the drafts, the gold side (lineage_spec.yml, traps.yml, pools.yml, the dev targets in
dev.jsonl), corpus files (absence and fact-line checks) and the set-E gold export. It never runs a
system. Output names draft ids, counts and check names only, never question text or gold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gen_dev_questions as g  # noqa: E402

from dlens import gold_spec as gs  # noqa: E402

DRAFTS = ROOT / "eval" / "questions" / "drafts"
TEST = DRAFTS / "test_draft_v1.jsonl"
EXTERNAL = DRAFTS / "external_draft_v1.jsonl"
EXPORT = DRAFTS / "external_gold_graph_v1.json"
DEV = ROOT / "eval" / "questions" / "dev.jsonl"
SS_DIR = ROOT / "corpora" / "synthetic_shop"

TRAPS9 = ["rename_chain", "select_star", "two_revenue_definitions", "deep_chain", "join_key_only",
          "fan_in_aggregate", "stale_doc", "near_duplicate_names", "exposures"]  # fmt: skip
TRAP_MIN = 4
NEAR_DUP_JACCARD = 0.85

# s15a-drafts-design.md §1 (test) and §2 (set E). Keys: see row_key().
TEST_ROWS: dict[tuple[str, ...], int] = {
    ("trace", "1", "upstream"): 16, ("trace", "1", "computed"): 2,
    ("trace", "1", "multi_part"): 1, ("trace", "1", "false_premise"): 2,
    ("trace", "2-3", "upstream"): 14, ("trace", "2-3", "computed"): 7,
    ("trace", "2-3", "ambiguous"): 2, ("trace", "2-3", "multi_part"): 2,
    ("trace", "2-3", "false_premise"): 3,
    ("trace", "4-5", "upstream"): 17, ("trace", "4-5", "computed"): 5,
    ("trace", "4-5", "ambiguous"): 2, ("trace", "4-5", "multi_part"): 2,
    ("trace", "4-5", "false_premise"): 2,
    ("trace", "6+", "upstream"): 15, ("trace", "6+", "computed"): 8,
    ("trace", "6+", "ambiguous"): 2, ("trace", "6+", "multi_part"): 2,
    ("trace", "6+", "false_premise"): 1,
    ("impact", "1"): 14, ("impact", "2-3"): 14, ("impact", "4-5"): 12, ("impact", "6+"): 11,
    ("impact", "indirect-only"): 5,
    ("yesno", "yes_direct"): 5, ("yesno", "yes_indirect_only"): 3, ("yesno", "no"): 6,
    ("ask",): 28,
    ("unanswerable", "dotted_near_miss"): 8, ("unanswerable", "dotted_typo"): 3,
    ("unanswerable", "unknown_model"): 3, ("unanswerable", "bare"): 4,
    ("unanswerable", "out_of_domain"): 3,
}  # fmt: skip
TEST_TYPES = {"trace": 105, "impact": 70, "ask": 28, "unanswerable": 21}
TEST_WORDING = {"identifier": 112, "paraphrase": 47, "description|name_words": 65}
TEST_DESCRIPTION_PLANNED = 23
TEST_INTERPRETED = 3
EXT_ROWS: dict[tuple[str, ...], int] = {
    ("trace", "1", "upstream"): 8, ("trace", "1", "computed"): 2,
    ("trace", "2-3", "upstream"): 7, ("trace", "2-3", "computed"): 3,
    ("trace", "4-5", "upstream"): 7, ("trace", "4-5", "computed"): 3,
    ("trace", "6+", "upstream"): 8, ("trace", "6+", "computed"): 2,
    ("impact", "1"): 5, ("impact", "2-3"): 5, ("impact", "4-5"): 3, ("impact", "6+"): 3,
    ("yesno", "yes_direct"): 2, ("yesno", "no"): 2,
}  # fmt: skip
EXT_TYPES = {"trace": 40, "impact": 20}
EXT_WORDING = {"identifier": 36, "paraphrase": 8, "description|name_words": 16}
EXT_DESCRIPTION_PLANNED = 6

REQUIRED = ["id", "draft_id", "corpus", "split", "type", "subtype", "question", "target", "mention",
            "hop_depth", "hop_bucket", "wording", "source", "traps", "gold", "gold_source",
            "expect", "source_lines", "review_flags", "review"]  # fmt: skip
TYPES = {"trace", "impact", "ask", "unanswerable"}
WORDINGS = {"identifier", "name_words", "description", "paraphrase"}
DECISIONS = {"pending", "keep", "fix", "drop"}
TOKEN = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)?")


@dataclass
class Report:
    failures: dict[str, list[str]] = field(default_factory=dict)
    info: list[str] = field(default_factory=list)
    short: dict[str, int] = field(default_factory=dict)

    def check(self, name: str, problems: Iterable[str]) -> None:
        self.failures[name] = sorted(set(problems))

    @property
    def ok(self) -> bool:
        return not any(self.failures.values())

    def render(self) -> str:
        lines = [*self.info, ""]
        for name, probs in self.failures.items():
            if probs:
                head = ", ".join(probs[:12]) + (
                    f" (+{len(probs) - 12} more)" if len(probs) > 12 else ""
                )
                lines.append(f"FAIL {name}: {head}")
            else:
                lines.append(f"PASS {name}")
        if self.short:
            lines.append(
                "still needed: " + ", ".join(f"{k} {v}" for k, v in sorted(self.short.items()))
            )
        return "\n".join(lines)


# --------------------------------------------------------------------------------- helpers
def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def row_key(q: Mapping[str, Any]) -> tuple[str, ...]:
    if q["type"] == "trace":
        return ("trace", str(q["hop_bucket"]), str(q["subtype"]))
    if q["type"] == "impact" and q["subtype"] == "yesno":
        reach = q["gold"]["reach"]
        if reach["all"] == "no":
            return ("yesno", "no")
        return ("yesno", "yes_direct" if reach["direct"] == "yes" else "yes_indirect_only")
    if q["type"] == "impact":
        return ("impact", str(q["hop_bucket"]))
    if q["type"] == "ask":
        return ("ask",)
    return ("unanswerable", str(q["subtype"]))


def tokens(text: str) -> set[str]:
    return set(TOKEN.findall(text.lower()))


def norm_text(text: str) -> str:
    return " ".join(TOKEN.findall(text.lower()))


def near_duplicates(
    rows: list[Mapping[str, Any]], others: list[Mapping[str, Any]] | None = None
) -> list[str]:
    """Pairs (by id) with equal normalised text or token Jaccard >= NEAR_DUP_JACCARD."""
    out = []
    a = [
        (str(q.get("draft_id") or q["id"]), tokens(q["question"]), norm_text(q["question"]))
        for q in rows
    ]
    b = (
        a
        if others is None
        else [(str(q["id"]), tokens(q["question"]), norm_text(q["question"])) for q in others]
    )
    for i, (ia, ta, na) in enumerate(a):
        for j, (ib, tb, nb) in enumerate(b):
            if others is None and j <= i:
                continue
            jac = len(ta & tb) / max(len(ta | tb), 1)
            if na == nb or jac >= NEAR_DUP_JACCARD:
                out.append(f"{ia}~{ib}")
    return out


def gold_columns(gold: Mapping[str, Any]) -> set[str]:
    """Every model.column id the gold names (fact text and `closest` names excluded)."""
    found: set[str] = set()

    def walk(x: Any, key: str = "") -> None:
        if key in ("facts", "closest", "out_of_scope", "text"):
            return
        if isinstance(x, Mapping):
            for k, v in x.items():
                walk(v, str(k))
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif isinstance(x, str) and gs.is_column_id(x) and key not in ("models",):
            found.add(x)

    walk(gold)
    return found


def check_counts(rows: list[Mapping[str, Any]], expected: Mapping[tuple[str, ...], int],
                 report: Report, name: str, allow_short: bool) -> None:  # fmt: skip
    got = Counter(row_key(q) for q in rows)
    probs = []
    for k, n in expected.items():
        if got[k] > n or (got[k] < n and not allow_short):
            probs.append(f"{'/'.join(k)} {got[k]}!={n}")
        elif got[k] < n:
            report.short["/".join(k)] = n - got[k]
    probs += [f"{'/'.join(k)} unexpected {n}" for k, n in got.items() if k not in expected]
    report.check(name, probs)


def check_types(rows: list[Mapping[str, Any]], expected: Mapping[str, int], report: Report,
                name: str, allow_short: bool) -> None:  # fmt: skip
    got = Counter(str(q["type"]) for q in rows)
    probs = [f"{t} {got[t]}!={n}" for t, n in expected.items()
             if got[t] > n or (got[t] < n and not allow_short)]  # fmt: skip
    probs += [f"{t} unexpected" for t in got if t not in expected]
    report.check(name, probs)


def check_wording(rows: list[Mapping[str, Any]], expected: Mapping[str, int], planned_desc: int,
                  report: Report, name: str, allow_short: bool) -> None:  # fmt: skip
    got = Counter(str(q["wording"]) for q in rows)
    got["description|name_words"] = got["description"] + got["name_words"]
    probs = [f"{w} {got[w]}!={n}" for w, n in expected.items()
             if got[w] > n or (got[w] < n and not allow_short)]  # fmt: skip
    report.check(name, probs)
    report.info.append(
        f"wording: {dict(sorted((k, v) for k, v in got.items() if '|' not in k))}; description "
        f"{got['description']} of {planned_desc} planned (the rest fell back to name_words, flagged)"
    )


def check_schema(
    rows: list[Mapping[str, Any]], split: str, corpus: str, gold_source: str
) -> list[str]:
    probs = []
    seen_ids: Counter[str] = Counter()
    for q in rows:
        did = str(q.get("draft_id", "?"))
        seen_ids[did] += 1
        seen_ids["id:" + str(q.get("id"))] += 1
        missing = [k for k in REQUIRED if k not in q]
        if missing:
            probs.append(f"{did} missing {','.join(missing)}")
            continue
        if q["split"] != split or q["corpus"] != corpus or q["gold_source"] != gold_source:
            probs.append(f"{did} split/corpus/gold_source")
        if q["type"] not in TYPES or q["wording"] not in WORDINGS:
            probs.append(f"{did} type/wording enum")
        if (q.get("review") or {}).get("decision") not in DECISIONS:
            probs.append(f"{did} review.decision")
        if q["wording"] == "paraphrase" and not q.get("template_question"):
            probs.append(f"{did} paraphrase without template_question")
        if "paraphrase_pending" in q["review_flags"]:
            probs.append(f"{did} paraphrase_pending")
        if not str(q["question"]).strip():
            probs.append(f"{did} empty question")
    probs += [f"duplicate {k}" for k, n in seen_ids.items() if n > 1]
    return probs


def check_d5(rows: list[Mapping[str, Any]]) -> list[str]:
    trace = Counter(q["target"] for q in rows if q["type"] == "trace")
    impact = Counter(q["target"] for q in rows if q["type"] == "impact")
    return [f"trace x{n} {t}" for t, n in trace.items() if n > 1] + [
        f"impact x{n} {t}" for t, n in impact.items() if n > 1
    ]


# ---------------------------------------------------------------------------- test (spec)
@dataclass
class SpecSide:
    ctx: g.Ctx
    dev_targets: set[str]
    dev_questions: list[dict[str, Any]]


def load_spec_side() -> SpecSide:
    dev = load_jsonl(DEV)
    return SpecSide(g.load_ctx(), {str(q["target"]) for q in dev}, dev)


def recompute_problems(q: Mapping[str, Any], ctx: g.Ctx) -> list[str]:
    """The gold fields that must equal the spec computation (dlens.gold_spec)."""
    t, gold, sub = str(q["target"]), q["gold"], q["subtype"]
    if q["type"] == "trace":
        if sub == "false_premise":
            p = gold["premise"]["edge"]["from"]
            want = g.gold_premise(ctx, p, t)
            keys = ["inputs", "premise"]
        elif sub == "computed":
            want, keys = g.gold_computed(ctx, t), ["inputs"]
        else:
            want, keys = g.gold_trace(ctx, t), ["inputs", "upstream", "sources"]
    elif q["type"] == "impact" and sub == "yesno":
        want = g.gold_reach(ctx, gold["reach"]["from"], gold["reach"]["to"])
        keys = ["reach"]
    elif q["type"] == "impact":
        want, keys = g.gold_impact(ctx, t), ["downstream", "models", "exposures"]
    else:
        return []
    return [f"{q['draft_id']} gold.{k}" for k in keys if gold.get(k) != want.get(k)]


def absent_problems(q: Mapping[str, Any], ctx: g.Ctx, corpus_dir: Path) -> list[str]:
    """An unanswerable mention must not exist in the spec, the model SQL, or as a model."""
    did, m = q["draft_id"], str(q["target"])
    ids = ctx.v.model_columns | ctx.v.seed_columns
    bare_all = {c.split(".")[1] for c in ids}
    sql = {p.stem: p.read_text() for p in (corpus_dir / "models").rglob("*.sql")}
    seeds = {p.stem for p in (corpus_dir / "seeds").glob("*.csv")}
    if "." not in m:
        snake = m.replace(" ", "_")
        if snake in bare_all or any(re.search(rf"\b{snake}\b", s) for s in sql.values()):
            return [f"{did} bare name exists"]
        return []
    model, col = m.split(".")
    if m in ids:
        return [f"{did} column exists"]
    if model in ctx.v.models or model in sql:
        if col in ctx.v.models.get(model, []) or re.search(rf"\b{col}\b", sql.get(model, "")):
            return [f"{did} column name appears in its model"]
        return []
    if model in seeds or model in ctx.v.seeds:
        return [f"{did} model is a seed"]
    return []  # unknown model: no SQL file and no seed of that name


def fact_problems(q: Mapping[str, Any], root: Path) -> list[str]:
    probs = []
    facts = q["gold"].get("facts") or []
    if not facts:
        return [f"{q['draft_id']} no facts"]
    for f in facts:
        src = str(f.get("source", ""))
        path, _, line = src.rpartition(":")
        p = root / path
        if not path.startswith("corpora/") or not line.isdigit() or not p.is_file():
            probs.append(f"{q['draft_id']} bad source")
            continue
        lines = p.read_text().splitlines()
        if not 1 <= int(line) <= len(lines) or not lines[int(line) - 1].strip():
            probs.append(f"{q['draft_id']} source line out of range or blank")
    if "stale_doc" in q["traps"] and not any(".sql:" in str(f.get("source")) for f in facts):
        probs.append(f"{q['draft_id']} stale-doc facts cite no SQL")
    return probs


def check_test(rows: list[dict[str, Any]], side: SpecSide, report: Report, allow_short: bool,
               corpus_dir: Path = SS_DIR, root: Path = ROOT) -> None:  # fmt: skip
    ctx = side.ctx
    ids = ctx.v.model_columns | ctx.v.seed_columns
    report.check("test: schema", check_schema(rows, "test", "synthetic_shop", "spec"))
    check_types(rows, TEST_TYPES, report, "test: counts per type", allow_short)
    check_counts(
        rows, TEST_ROWS, report, "test: counts per row (type x hop bucket x subtype)", allow_short
    )
    check_wording(
        rows, TEST_WORDING, TEST_DESCRIPTION_PLANNED, report, "test: wording mix", allow_short
    )

    # traps: all 9 covered (>= 1), and the ones under TRAP_MIN reported
    traps = Counter(t for q in rows for t in q["traps"])
    report.check("test: all 9 traps covered", [t for t in TRAPS9 if traps[t] == 0])
    under = [f"{t} {traps[t]}" for t in TRAPS9 if 0 < traps[t] < TRAP_MIN]
    report.info.append(f"traps: {dict(sorted(traps.items()))}; under {TRAP_MIN}: {under or 'none'}")

    # gold nodes exist in the spec; gold recomputes from the spec
    expos = set(ctx.exposures)
    node_probs = []
    for q in rows:
        missing = gold_columns(q["gold"]) - ids
        bad_x = {x for k in ("direct", "all")
                 for x in ((q["gold"].get("exposures") or {}).get(k) or [])} - expos  # fmt: skip
        if missing or bad_x:
            node_probs.append(f"{q['draft_id']} {len(missing) + len(bad_x)} unknown nodes")
    report.check("test: every gold node exists in the gold spec", node_probs)
    report.check("test: gold recomputes from the gold spec",
                 [p for q in rows for p in recompute_problems(q, ctx)])  # fmt: skip

    # column split vs dev
    disj = []
    for q in rows:
        if q["type"] in ("trace", "impact", "ask"):
            if q["target"] in side.dev_targets or q["target"] not in ctx.test:
                disj.append(f"{q['draft_id']} target")
        for m in g.DOTTED.findall(q["question"]):
            if m in ctx.dev or m in side.dev_targets:
                disj.append(f"{q['draft_id']} names a dev column")
    report.check("test: column-disjoint from dev", disj)

    report.check("test: no near-duplicates vs dev", near_duplicates(rows, side.dev_questions))
    report.check("test: D5 (<= 1 trace, <= 1 impact per column)", check_d5(rows))
    report.check("test: unanswerable targets absent from the corpus",
                 [p for q in rows if q["type"] == "unanswerable"
                  for p in absent_problems(q, ctx, corpus_dir)])  # fmt: skip
    report.check("test: Ask facts cite existing file:line",
                 [p for q in rows if q["type"] == "ask" for p in fact_problems(q, root)])  # fmt: skip

    # exposures focus and interpretations
    focus = [q for q in rows if q["gold"].get("focus") == "exposures"]
    one = [q for q in focus if len(q["gold"]["exposures"]["all"]) == 1]
    interp = [q for q in rows if "interpretation" in q["gold"]]
    ip = [f"{q['draft_id']} interpretation" for q in interp
          if q["gold"]["interpretation"]["column"] != q["target"]
          or q["gold"]["interpretation"]["text"] in ids]  # fmt: skip
    if len(focus) < 3 or not one:
        ip.append(f"exposures focus {len(focus)} (one dashboard {len(one)})")
    if len(interp) != TEST_INTERPRETED:
        ip.append(f"interpreted {len(interp)}!={TEST_INTERPRETED}")
    report.check("test: exposures focus and interpreted near-misses", ip)

    buckets = Counter(
        f"{q['type']}:{q['hop_bucket']}" for q in rows if q["type"] in ("trace", "impact")
    )
    report.info.insert(
        0, f"test: {len(rows)} drafts; types {dict(Counter(q['type'] for q in rows))}"
    )
    report.info.insert(1, f"test hop buckets: {dict(sorted(buckets.items()))}")


# ------------------------------------------------------------------------- set E (parser)
def export_sha(export_text: str) -> str:
    return hashlib.sha256(export_text.encode()).hexdigest()


def check_external(rows: list[dict[str, Any]], export_text: str, report: Report, allow_short: bool,
                   ext_rows: Mapping[tuple[str, ...], int] | None = None) -> None:  # fmt: skip
    export = json.loads(export_text)
    meta = export["meta"]
    nodes = set(export["nodes"])
    report.check("set E: schema", check_schema(rows, "external", "dbt_jira", "parser"))
    check_types(rows, EXT_TYPES, report, "set E: counts per type", allow_short)
    if ext_rows is None:
        ext_rows = EXT_ROWS
    check_counts(rows, ext_rows, report, "set E: counts per row (type x hop bucket)", allow_short)
    check_wording(
        rows, EXT_WORDING, EXT_DESCRIPTION_PLANNED, report, "set E: wording mix", allow_short
    )
    sha = export_sha(export_text)
    meta_probs = []
    for q in rows:
        gm = q.get("gold_meta") or {}
        if gm.get("graph_sha256") != meta["graph_sha256"] or gm.get("export_sha256") != sha:
            meta_probs.append(f"{q['draft_id']} gold_meta hash")
        if gm.get("dlens_version") != meta["dlens_version"]:
            meta_probs.append(f"{q['draft_id']} gold_meta engine version")
    report.check("set E: graph_sha256 / export hash / engine version recorded", meta_probs)
    report.check("set E: every gold node exists in the graph",
                 [f"{q['draft_id']} {len(gold_columns(q['gold']) - nodes)} unknown nodes"
                  for q in rows if gold_columns(q["gold"]) - nodes])  # fmt: skip
    report.check("set E: D5 (<= 1 trace, <= 1 impact per column)", check_d5(rows))
    buckets = Counter(f"{q['type']}:{q['hop_bucket']}" for q in rows)
    report.info.append(f"set E: {len(rows)} drafts; hop buckets {dict(sorted(buckets.items()))}")
    report.info.append(
        f"set E graph: dlens {meta['dlens_version']}, graph_sha256 {meta['graph_sha256'][:12]}…"
    )


# ------------------------------------------------------------------------------------ main
def run(test_path: Path, ext_path: Path, export_path: Path, allow_short: bool) -> Report:
    report = Report()
    test_rows = load_jsonl(test_path) if test_path.is_file() else []
    ext_rows = load_jsonl(ext_path) if ext_path.is_file() else []
    report.check("files present", [str(p.name) for p in (test_path, ext_path, export_path)
                                   if not p.is_file()])  # fmt: skip
    if test_rows:
        check_test(test_rows, load_spec_side(), report, allow_short)
    if ext_rows and export_path.is_file():
        check_external(ext_rows, export_path.read_text(), report, allow_short)
    report.check("no near-duplicates within the drafts", near_duplicates(test_rows + ext_rows))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--test", type=Path, default=TEST)
    ap.add_argument("--external", type=Path, default=EXTERNAL)
    ap.add_argument("--export", type=Path, default=EXPORT)
    ap.add_argument(
        "--allow-short",
        action="store_true",
        help="report counts below the table instead of failing (after review drops)",
    )
    args = ap.parse_args()
    report = run(args.test, args.external, args.export, args.allow_short)
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
