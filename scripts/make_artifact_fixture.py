"""Build the committed artifact fixtures for artifact-only ingest tests (S06, ADR 0013).

    uv run python scripts/make_artifact_fixture.py eph_shop        # tests/fixtures/artifacts/eph_shop/target
    uv run python scripts/make_artifact_fixture.py synthetic_shop  # tests/fixtures/artifacts/synthetic_shop

Each project is built with dbt-duckdb in a temp copy (the repo stays free of *.duckdb). Only
manifest.json, catalog.json (and, for eph_shop, compiled/; its manifest loses only the built-in
``macros`` and ``docs`` sections) are kept, and every absolute path is
removed: ``root_path`` keys are dropped and any string holding the build directory is made
relative. synthetic_shop's manifest is trimmed to the fields DLens reads, so the fixture stays
small enough to commit; it backs the dialect tests, which then run without dbt.
"""

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from dlens.ingest.runner import run_dbt

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "artifacts"
SOURCES = {
    "eph_shop": FIXTURES / "eph_shop",
    "synthetic_shop": ROOT / "corpora" / "synthetic_shop",
}
# Manifest fields DLens reads (dlens.ingest.artifacts), kept by the synthetic_shop trim.
NODE_FIELDS = (
    "unique_id",
    "resource_type",
    "name",
    "relation_name",
    "original_file_path",
    "compiled_code",
    "depends_on",
    "package_name",
    "database",
    "schema",
    "alias",
    "identifier",
    "columns",
    "config",
    # Text the S07 chunker reads (descriptions and where they are written).
    "description",
    "patch_path",
    "source_name",
)
METADATA_FIELDS = ("dbt_schema_version", "dbt_version", "adapter_type", "project_name")


def sanitize(obj: Any, build_dir: str) -> Any:
    """Drop ``root_path`` keys and make any string that holds ``build_dir`` relative."""
    if isinstance(obj, dict):
        return {k: sanitize(v, build_dir) for k, v in obj.items() if k != "root_path"}
    if isinstance(obj, list):
        return [sanitize(v, build_dir) for v in obj]
    if isinstance(obj, str) and build_dir in obj:
        return obj.replace(build_dir + "/", "").replace(build_dir, ".")
    return obj


def trim_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Models, seeds, sources and exposures with only the fields DLens reads."""

    def node(n: dict[str, Any]) -> dict[str, Any]:
        out = {k: n[k] for k in NODE_FIELDS if k in n}
        out["depends_on"] = {"nodes": n.get("depends_on", {}).get("nodes", [])}
        out["config"] = {"materialized": n.get("config", {}).get("materialized")}
        out["columns"] = {
            k: {
                "name": c["name"],
                "data_type": c.get("data_type"),
                "description": c.get("description", ""),
            }
            for k, c in n.get("columns", {}).items()
        }
        return out

    keep = {"model", "seed"}
    return {
        "metadata": {k: manifest["metadata"].get(k) for k in METADATA_FIELDS},
        "nodes": {
            k: node(v) for k, v in sorted(manifest["nodes"].items()) if v["resource_type"] in keep
        },
        "sources": {k: node(v) for k, v in sorted(manifest.get("sources", {}).items())},
        "exposures": {
            k: {
                "unique_id": v["unique_id"],
                "name": v["name"],
                "type": v["type"],
                "depends_on": {"nodes": v.get("depends_on", {}).get("nodes", [])},
                "package_name": v.get("package_name"),
                "original_file_path": v.get("original_file_path"),
                "label": v.get("label"),
                "description": v.get("description", ""),
                "owner": {"name": (v.get("owner") or {}).get("name")},
            }
            for k, v in sorted(manifest.get("exposures", {}).items())
        },
        "docs": {
            k: {
                f: v.get(f)
                for f in ("name", "package_name", "original_file_path", "block_contents")
            }
            for k, v in sorted(manifest.get("docs", {}).items())
            if v.get("package_name") != "dbt"
        },
    }


def trim_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "metadata": {"dbt_schema_version": catalog["metadata"]["dbt_schema_version"]},
        "nodes": dict(sorted(catalog.get("nodes", {}).items())),
        "sources": dict(sorted(catalog.get("sources", {}).items())),
    }


def _dump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def build(name: str) -> dict[str, Any]:
    """Build NAME in a temp copy; return {relative path: content} for the fixture."""
    src = SOURCES[name]
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / name
        shutil.copytree(src, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs"))
        target = run_dbt(project).target_dir
        build_dir = str(project)
        manifest = sanitize(json.loads((target / "manifest.json").read_text()), build_dir)
        catalog = sanitize(json.loads((target / "catalog.json").read_text()), build_dir)
        if name == "synthetic_shop":
            return {"manifest.json": trim_manifest(manifest), "catalog.json": trim_catalog(catalog)}
        # eph_shop keeps the real manifest, minus dbt's ~700 KB of built-in macros and docs
        # (the project's own docs blocks stay: S07 chunks them).
        manifest = {k: v for k, v in manifest.items() if k != "macros"}
        manifest["docs"] = {
            k: v for k, v in manifest.get("docs", {}).items() if v.get("package_name") != "dbt"
        }
        files: dict[str, Any] = {"manifest.json": manifest, "catalog.json": catalog}
        for sql in sorted((target / "compiled").rglob("*.sql")):
            files[sql.relative_to(target).as_posix()] = sql.read_text()
        return files


VOLATILE_METADATA = {
    "generated_at",
    "invocation_id",
    "invocation_started_at",
    "run_started_at",
    "user_id",  # dbt's anonymous per-machine id: volatile and not ours to commit
}


def _drop_created_at(manifest: dict[str, Any]) -> dict[str, Any]:
    """Drop the per-node ``created_at`` build timestamp (only that key: a column may also be
    called created_at, and the catalog is never touched)."""
    out = dict(manifest)
    for section in ("nodes", "sources", "exposures"):
        if section in out:
            out[section] = {
                k: {f: v for f, v in node.items() if f != "created_at"}
                for k, node in out[section].items()
            }
    return out


def volatile_free(files: dict[str, Any]) -> dict[str, Any]:
    """The fixture without fields that change on every build (ids and timestamps)."""
    out = dict(files)
    for key in ("manifest.json", "catalog.json"):
        meta = {k: v for k, v in out[key]["metadata"].items() if k not in VOLATILE_METADATA}
        out[key] = {**out[key], "metadata": meta}
    out["manifest.json"] = _drop_created_at(out["manifest.json"])
    return out


def output_dir(name: str) -> Path:
    return FIXTURES / name / "target" if name == "eph_shop" else FIXTURES / name


def write(name: str, files: dict[str, Any]) -> None:
    out = output_dir(name)
    if out.exists():
        shutil.rmtree(out)
    for rel, content in files.items():
        if isinstance(content, str):
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_text(content, encoding="utf-8")
        else:
            _dump(content, out / rel)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("name", choices=sorted(SOURCES))
    args = parser.parse_args()
    write(args.name, volatile_free(build(args.name)))
    print(f"wrote {output_dir(args.name).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
