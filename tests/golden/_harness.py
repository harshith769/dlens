"""Golden-test harness: run the engine on one SQL fixture with an inline schema, no dbt."""

import json
from dataclasses import dataclass
from pathlib import Path

from dlens.ingest import IngestResult
from dlens.ingest.artifacts import Catalog, Manifest
from dlens.lineage import extract_lineage, short_id

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
    result = extract_lineage(ingest, Path("/nonexistent"))
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
    )


def fixture_names() -> list[str]:
    return sorted(p.name.removesuffix(".sql") for p in FIXTURES.glob("*.sql"))


def load_expected(name: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((FIXTURES / f"{name}.expected.json").read_text())
    return data


def run_fixture(name: str) -> Result:
    return run_sql((FIXTURES / f"{name}.sql").read_text())


# S03 step 3a: the indirect expectations are written from ADR 0020 before the engine emits any
# indirect edge. While True, fixtures that expect indirect edges are strict xfails.
INDIRECT_PENDING = True


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
    key, or deferred keys), else yes."""
    rows = ["| Construct | Supported | Note |", "|---|---|---|"]
    for name in fixture_names():
        exp = load_expected(name)
        if exp.get("xfail"):
            level, note = "no", str(exp["xfail"])
        elif INDIRECT_PENDING and exp["indirect"]:
            level = "partial"
            note = "indirect edges are expected; the engine does not emit them yet"
        elif exp.get("partial") or exp.get("deferred"):
            level = "partial"
            note = str(exp.get("partial") or "window PARTITION BY / ORDER BY keys are deferred")
        else:
            level, note = "yes", str(exp.get("notes", ""))
        rows.append(f"| `{name}` | {level} | {note} |")
    rows += [f"| {name} | no (untested) | {note} |" for name, note in UNTESTED]
    return "\n".join(rows)
