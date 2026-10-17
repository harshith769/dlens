"""Dialect round trip for artifact ingest (S06, ADR 0013).

    uv run python scripts/dialect_check.py      # writes eval/reports/s06_dialects.json

Takes the committed synthetic_shop artifacts (tests/fixtures/artifacts/synthetic_shop), transpiles
every model's compiled SQL from DuckDB to each target dialect with sqlglot, converts the catalog
types the same way, renders relation names the way that adapter writes them, and ingests the fake
artifacts with ``load_target`` (adapter_type = the dialect). Direct and indirect edges are scored
against the hand-written gold (lineage_spec.yml) exactly as the DuckDB baseline is.

What this tests: sqlglot's DuckDB -> X round trip plus our dialect handling. It does NOT test
real-world SQL written by hand for that warehouse.

The only normalisation in the comparison is identifier case: column ids are lowercased
(``column_id`` / ``short_id``), because Snowflake reports unquoted identifiers in upper case.
Nothing else is rewritten, matched loosely or ignored.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import sqlglot
import yaml
from sqlglot import exp

from dlens.gold_spec import expand_indirect
from dlens.ingest import load_target
from dlens.lineage import compare, compare_indirect, extract_lineage, short_id

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "artifacts" / "synthetic_shop"
SPEC = ROOT / "corpora" / "synthetic_shop" / "lineage_spec.yml"
REPORT = ROOT / "eval" / "reports" / "s06_dialects.json"
DIALECTS = ("snowflake", "bigquery", "postgres")
MAX_DROP = 0.02


def _relation(parts: list[str], dialect: str) -> str:
    """relation_name as the adapter writes it: Snowflake unquoted (dbt-snowflake's default
    quoting), BigQuery backticks, Postgres double quotes."""
    if dialect == "snowflake":
        return ".".join(parts)
    q = "`" if dialect == "bigquery" else '"'
    return ".".join(f"{q}{p}{q}" for p in parts)


def transpile_sql(sql: str, dialect: str) -> str:
    tree = sqlglot.parse_one(sql, read="duckdb")
    if dialect == "snowflake":
        for table in tree.find_all(exp.Table):  # dbt-snowflake renders relations unquoted
            for part in (table.args.get(k) for k in ("catalog", "db", "this")):
                if isinstance(part, exp.Identifier):
                    part.set("quoted", False)
    return tree.sql(dialect=dialect, pretty=True)


def transpile_type(t: str, dialect: str) -> str:
    try:
        return exp.DataType.build(t, dialect="duckdb").sql(dialect)
    except Exception:  # an unknown type stays as written
        return t


def fake_artifacts(dialect: str, out: Path) -> Path:
    """manifest.json + catalog.json for DIALECT in OUT (a target/ dir)."""
    manifest: dict[str, Any] = json.loads((FIXTURE / "manifest.json").read_text())
    catalog: dict[str, Any] = json.loads((FIXTURE / "catalog.json").read_text())
    manifest["metadata"]["adapter_type"] = dialect
    upper = dialect == "snowflake"  # Snowflake's catalog reports unquoted names in upper case
    for section in ("nodes", "sources"):
        for node in manifest.get(section, {}).values():
            if node.get("relation_name"):
                parts = [p.strip('"') for p in node["relation_name"].split(".")]
                node["relation_name"] = _relation(parts, dialect)
            if node.get("compiled_code"):
                node["compiled_code"] = transpile_sql(node["compiled_code"], dialect)
        for entry in catalog.get(section, {}).values():
            meta = entry["metadata"]
            for k in ("database", "schema", "name"):
                if upper and meta.get(k):
                    meta[k] = meta[k].upper()
            entry["columns"] = {
                (n.upper() if upper else n): {
                    **c,
                    "name": c["name"].upper() if upper else c["name"],
                    "type": transpile_type(c["type"], dialect),
                }
                for n, c in entry["columns"].items()
            }
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (out / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    return out


def _gold() -> tuple[list[dict[str, str]], list[tuple[str, str, str]]]:
    spec = yaml.safe_load(SPEC.read_text())
    direct = [g for g in spec["edges"] if g["phase"] == "v0.1"]
    models = {m: list(v["columns"]) for m, v in spec["models"].items()}
    pairs = expand_indirect(
        spec["indirect_edges"], models, {(e["from"], e["to"]) for e in spec["edges"]}
    ).pairs
    return direct, [(p.from_column, p.to_column, p.type) for p in pairs]


def score(target: Path) -> dict[str, Any]:
    ingested, info = load_target(target)
    result = extract_lineage(ingested, target, info.dialect)
    gold_direct, gold_indirect = _gold()
    d = compare(result.edges, gold_direct)
    i = compare_indirect(result.indirect, gold_indirect)
    return {
        "dialect": info.dialect,
        "direct_f1": round(d.f1, 4),
        "indirect_f1": round(i.overall.f1, 4),
        "quality": {
            q: sum(str(p.quality) == q for p in result.parse_report.values())
            for q in ("FULL", "TABLE_ONLY", "FAILED")
        },
        "failed": {u: p.reason for u, p in result.parse_report.items() if p.reason},
        "direct": sorted(
            f"{short_id(e.from_column)} -> {short_id(e.to_column)}" for e in result.edges
        ),
        "indirect": sorted(
            f"{short_id(e.from_column)} -> {short_id(e.to_column)} {e.kind}"
            for e in result.indirect
        ),
    }


def run() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        base = score(FIXTURE)
        rows = {}
        for dialect in DIALECTS:
            s = score(fake_artifacts(dialect, Path(tmp) / dialect))
            rows[dialect] = {
                "direct_f1": s["direct_f1"],
                "indirect_f1": s["indirect_f1"],
                "direct_drop": round(base["direct_f1"] - s["direct_f1"], 4),
                "indirect_drop": round(base["indirect_f1"] - s["indirect_f1"], 4),
                "quality": s["quality"],
                "lost_direct": sorted(set(base["direct"]) - set(s["direct"])),
                "gained_direct": sorted(set(s["direct"]) - set(base["direct"])),
                "lost_indirect": sorted(set(base["indirect"]) - set(s["indirect"])),
                "gained_indirect": sorted(set(s["indirect"]) - set(base["indirect"])),
                "not_full": s["failed"],
            }
    return {
        "what": "sqlglot round trip DuckDB -> dialect on synthetic_shop compiled SQL, scored "
        "against lineage_spec.yml; not real-world dialect SQL",
        "normalisation": "identifier case only (column ids lowercased)",
        "max_drop": MAX_DROP,
        "sqlglot": sqlglot.__version__,
        "duckdb": {"direct_f1": base["direct_f1"], "indirect_f1": base["indirect_f1"]},
        "dialects": rows,
    }


def main() -> None:
    report = run()
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"duckdb     direct {report['duckdb']['direct_f1']:.4f}  indirect {report['duckdb']['indirect_f1']:.4f}"
    )
    for d, r in report["dialects"].items():
        print(
            f"{d:<10} direct {r['direct_f1']:.4f}  indirect {r['indirect_f1']:.4f}  "
            f"lost {len(r['lost_direct'])}/{len(r['lost_indirect'])}  "
            f"gained {len(r['gained_direct'])}/{len(r['gained_indirect'])}  {r['quality']}"
        )
    print(f"wrote {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
