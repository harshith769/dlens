"""Golden-test harness: run the engine on one SQL fixture with an inline schema, no dbt."""

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dlens.ingest import IngestResult
from dlens.ingest.artifacts import Catalog, Manifest
from dlens.lineage import IndirectEdge, extract_lineage, short_id

FIXTURES = Path(__file__).parent / "fixtures"
MODEL = "model.p.m"

_TABLES = {
    "orders": {
        "id": "int",
        "user_id": "int",
        "amt": "int",
        "tax": "int",
        "status": "varchar",
        "order_date": "date",
    },
    "customers": {"id": "int", "name": "varchar", "region": "varchar"},
    "order_items": {"order_id": "int", "product_id": "int", "qty": "int", "price": "int"},
    "products": {"id": "int", "title": "varchar", "list_price": "int"},
    "employees": {"id": "int", "name": "varchar", "manager_id": "int"},
    "refunds": {"id": "int", "order_id": "int", "refund_amt": "int"},
    "payments": {"id": "int", "order_id": "int", "pay_amt": "int"},
}
SCHEMA = {"db": {"main": _TABLES}}
RELATIONS = {f"db.main.{t}": f"seed.p.{t}" for t in _TABLES}


@dataclass(frozen=True)
class Result:
    edges: set[tuple[str, str, str]]  # (from, to, kind) as short ids
    quality: str
    constants: list[str]
    deferred: set[tuple[str, str]]
    indirect: set[tuple[str, str, str]]  # (from, to, type) as short ids
    indirect_edges: list[IndirectEdge]
    source: str  # the fixture SQL, written as the model's source file models/m.sql


def run_sql(sql: str) -> Result:
    model = {
        "unique_id": MODEL,
        "resource_type": "model",
        "name": "m",
        "original_file_path": "models/m.sql",
        "compiled_code": sql,
        "depends_on": {"nodes": []},
    }
    ingest = IngestResult(
        manifest=Manifest.model_validate({"nodes": {MODEL: model}, "exposures": {}}),
        catalog=Catalog(tables=[]),
        schema=SCHEMA,
        relation_map=RELATIONS,
        unmapped=[],
    )
    with tempfile.TemporaryDirectory() as tmp:  # the fixture is its own source file
        (Path(tmp) / "models").mkdir()
        (Path(tmp) / "models" / "m.sql").write_text(sql)
        result = extract_lineage(ingest, Path(tmp))
    parse = result.parse_report[MODEL]
    return Result(
        edges={(short_id(e.from_column), short_id(e.to_column), str(e.kind)) for e in result.edges},
        quality=str(parse.quality),
        constants=parse.constants,
        deferred={
            (short_id(d.from_column), short_id(d.to_column)) for d in parse.deferred_indirect
        },
        indirect={
            (short_id(e.from_column), short_id(e.to_column), str(e.kind))
            for e in getattr(result, "indirect", [])
        },
        indirect_edges=list(result.indirect),
        source=sql,
    )


def key_is_cited(key: str, chunk: str) -> bool:
    """The cited clause holds the key as written: its column name (last segment of the qualified
    key), a GROUP BY / ORDER BY position (``1``) or the ``ALL`` of GROUP BY ALL."""
    token = key.replace('"', "").split(".")[-1]
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", chunk, re.IGNORECASE) is not None


def cited_chunk(e: IndirectEdge, source: str) -> str:
    return "\n".join(source.splitlines()[e.lines[0] - 1 : e.lines[1]])


def fixture_names() -> list[str]:
    return sorted(p.name.removesuffix(".sql") for p in FIXTURES.glob("*.sql"))


def load_expected(name: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((FIXTURES / f"{name}.expected.json").read_text())
    return data


def run_fixture(name: str) -> Result:
    return run_sql((FIXTURES / f"{name}.sql").read_text())


def expected_indirect(name: str) -> set[tuple[str, str, str]]:
    rows = load_expected(name)["indirect"]  # required in every fixture
    assert isinstance(rows, list)
    return {(r["from"], r["to"], r["type"]) for r in rows}


MATRIX_START = "<!-- support-matrix:start -->"
MATRIX_END = "<!-- support-matrix:end -->"


# Constructs with no fixture: behaviour is not guaranteed and nothing guards it.
UNTESTED = [
    (
        "star join with duplicate column names",
        "`SELECT *` over a join whose sides share a column name; no fixture, so the output "
        "columns and their edges are not guaranteed",
    ),
]


def support_matrix_md() -> str:
    """Markdown table generated from the fixtures (plus UNTESTED).

    no = strict xfail, partial = a fixture that documents what it does not capture (``partial``
    key), else yes. Deferred window keys are also WINDOW indirect edges since S03 (ADR 0020)."""
    rows = ["| Construct | Supported | Note |", "|---|---|---|"]
    for name in fixture_names():
        exp = load_expected(name)
        if exp.get("xfail"):
            level, note = "no", str(exp["xfail"])
        elif exp.get("partial"):
            level, note = "partial", str(exp["partial"])
        else:
            level, note = "yes", str(exp.get("notes", ""))
        rows.append(f"| `{name}` | {level} | {note} |")
    rows += [f"| {name} | no (untested) | {note} |" for name, note in UNTESTED]
    return "\n".join(rows)
