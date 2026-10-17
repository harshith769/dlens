"""Compile a dbt corpus and run its compiled SQL in an in-memory DuckDB (oracle-design.md §1, §2).

Independence (oracle-design.md §0): this module never imports the dlens engine. It runs dbt itself
(``seed`` + ``compile``, never ``build`` and never tests) and reads only ``manifest.json``.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb
import yaml

BASE = "base"  # schema holding the pristine tables; perturbed runs work in "main"


class OracleError(RuntimeError):
    """dbt failed, or the corpus can't be executed as the oracle needs."""


def find_dbt() -> Path:
    """dbt from the same environment as this interpreter, else the one on PATH."""
    sibling = Path(sys.executable).parent / "dbt"
    if sibling.is_file():
        return sibling
    found = shutil.which("dbt")
    if found:
        return Path(found)
    raise OracleError("dbt executable not found next to the Python interpreter or on PATH.")


@dataclass(frozen=True)
class Model:
    name: str
    sql: str  # compiled SELECT, exactly as dbt wrote it
    parents: tuple[str, ...]  # seed and model names, manifest order
    path: str = ""  # project-relative source file (manifest original_file_path)


@dataclass
class Corpus:
    """Seeds and models (in topological order) of one compiled dbt project."""

    catalog: str  # database name the compiled SQL uses ("synthetic_shop")
    seeds: list[str]
    models: dict[str, Model]  # insertion order is a topological order
    db_path: Path  # dbt-seeded DuckDB file the seed tables are copied from
    children: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.children = {name: [] for name in [*self.seeds, *self.models]}
        for model in self.models.values():
            for parent in model.parents:
                self.children[parent].append(model.name)

    def descendants(self, table: str) -> list[str]:
        """Every model that (transitively) reads ``table``, in topological order."""
        reached = {table}
        out = []
        for model in self.models.values():
            if reached.intersection(model.parents):
                reached.add(model.name)
                out.append(model.name)
        return out


def _run_dbt(args: list[str], project: Path) -> None:
    cmd = [str(find_dbt()), *args, "--project-dir", str(project), "--profiles-dir", str(project)]
    result = subprocess.run(cmd, cwd=project, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-20:])
        raise OracleError(f"`dbt {' '.join(args)}` failed (exit {result.returncode}):\n{tail}")


def compile_corpus(corpus_dir: Path, work_dir: Path) -> Corpus:
    """Copy the corpus into ``work_dir``, then ``dbt seed`` and ``dbt compile`` its models."""
    project = work_dir / corpus_dir.name
    shutil.copytree(
        corpus_dir, project, ignore=shutil.ignore_patterns("target", "*.duckdb", "logs")
    )
    _run_dbt(["seed"], project)
    _run_dbt(["compile", "--select", "resource_type:model"], project)
    manifest = json.loads((project / "target" / "manifest.json").read_text())
    return corpus_from_manifest(manifest, project)


def corpus_from_manifest(manifest: Mapping[str, Any], project: Path) -> Corpus:
    nodes = manifest["nodes"]
    seeds = {uid: n for uid, n in nodes.items() if n["resource_type"] == "seed"}
    models = {uid: n for uid, n in nodes.items() if n["resource_type"] == "model"}
    names = {uid: n["name"] for uid, n in {**seeds, **models}.items()}
    catalogs = {n["database"] for n in models.values()}
    if len(catalogs) != 1:
        raise OracleError(f"models span several databases: {sorted(catalogs)}")
    order = _topological(
        {uid: [d for d in n["depends_on"]["nodes"] if d in models] for uid, n in models.items()}
    )
    built = {}
    for uid in order:
        node = models[uid]
        if not node.get("compiled_code"):
            raise OracleError(f"{node['name']} has no compiled_code; run dbt compile first")
        parents = tuple(names[d] for d in node["depends_on"]["nodes"] if d in names)
        built[node["name"]] = Model(
            node["name"], node["compiled_code"], parents, node.get("original_file_path", "")
        )
    profile_path = _duckdb_path(project)
    return Corpus(catalogs.pop(), sorted(n["name"] for n in seeds.values()), built, profile_path)


def _duckdb_path(project: Path) -> Path:
    profiles = yaml.safe_load((project / "profiles.yml").read_text())
    profile = profiles[next(iter(profiles))]
    path = Path(profile["outputs"][profile["target"]]["path"])
    return path if path.is_absolute() else project / path


def _topological(deps: Mapping[str, list[str]]) -> list[str]:
    """Kahn's algorithm; ties broken by unique_id so the order is deterministic."""
    remaining = {k: set(v) for k, v in deps.items()}
    order: list[str] = []
    while remaining:
        ready = sorted(k for k, v in remaining.items() if not v)
        if not ready:
            raise OracleError(f"dependency cycle among {sorted(remaining)}")
        for k in ready:
            order.append(k)
            del remaining[k]
        for v in remaining.values():
            v.difference_update(ready)
    return order


# ------------------------------------------------------------------------------------ fingerprint
@dataclass(frozen=True)
class Fingerprint:
    """Row count plus one hash per column of its sorted value multiset (row order ignored)."""

    rows: int
    columns: dict[str, str]  # column -> sha256 of the sorted canonical values

    def changed(self, base: "Fingerprint") -> list[str]:
        """Columns that differ from ``base``; every column when the row count differs."""
        if self.rows != base.rows:
            return list(base.columns)
        return [c for c, h in base.columns.items() if self.columns.get(c) != h]


def canonical(value: object) -> str:
    """One string per value; equal values give equal strings. Doubles keep 10 significant digits."""
    if value is None:
        return "\x00NULL"
    if isinstance(value, bool):
        return f"b:{value}"
    if isinstance(value, float):
        return f"f:{value:.10g}"
    if isinstance(value, int | Decimal):
        return f"n:{value}"
    if isinstance(value, datetime | date):
        return f"t:{value.isoformat()}"
    return f"s:{value!r}"


def fingerprint(names: Sequence[str], rows: Iterable[Sequence[object]]) -> Fingerprint:
    data = list(rows)
    hashes = {}
    for i, name in enumerate(names):
        values = sorted(canonical(r[i]) for r in data)
        hashes[name] = sha256("\x01".join(values).encode()).hexdigest()
    return Fingerprint(len(data), hashes)


# -------------------------------------------------------------------------------------- warehouse
class Warehouse:
    """The corpus in an in-memory DuckDB: seeds and models as tables, pristine copies in BASE."""

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self.con = duckdb.connect(":memory:")
        cat = corpus.catalog
        self.con.execute(f'ATTACH \':memory:\' AS "{cat}"; USE "{cat}"; SET threads = 1')
        self.con.execute(f"CREATE SCHEMA {BASE}")
        self.con.execute(f"ATTACH '{corpus.db_path}' AS __src (READ_ONLY)")
        for seed in corpus.seeds:
            self.con.execute(f'CREATE TABLE main."{seed}" AS SELECT * FROM __src.main."{seed}"')
        self.con.execute("DETACH __src")
        for name in corpus.models:
            self.materialise(name)
        for name in [*corpus.seeds, *corpus.models]:
            self.con.execute(f'CREATE TABLE {BASE}."{name}" AS SELECT * FROM main."{name}"')
        self._types = {t: self._describe(t) for t in [*corpus.seeds, *corpus.models]}

    def _describe(self, table: str) -> dict[str, str]:
        rows = self.con.execute(f'DESCRIBE {BASE}."{table}"').fetchall()
        return {r[0]: r[1] for r in rows}

    def types(self, table: str) -> dict[str, str]:
        return self._types[table]

    def materialise(self, model: str) -> None:
        self.con.execute(
            f'CREATE OR REPLACE TABLE main."{model}" AS {self.corpus.models[model].sql}'
        )

    def restore(self, table: str) -> None:
        self.con.execute(
            f'CREATE OR REPLACE TABLE main."{table}" AS SELECT * FROM {BASE}."{table}"'
        )

    def query_fingerprint(self, sql: str) -> Fingerprint:
        cur = self.con.execute(sql)
        names = [d[0] for d in cur.description]
        return fingerprint(names, cur.fetchall())

    def table_fingerprint(self, table: str, schema: str = "main") -> Fingerprint:
        return self.query_fingerprint(f'SELECT * FROM {schema}."{table}"')

    def model_fingerprint(self, model: str) -> Fingerprint:
        """Run the model's compiled SELECT on the current ``main`` tables, without storing it."""
        return self.query_fingerprint(self.corpus.models[model].sql)

    def column_values(self, table: str, column: str) -> list[object]:
        sql = f'SELECT "{column}" FROM {BASE}."{table}" ORDER BY rowid'
        return [r[0] for r in self.con.execute(sql).fetchall()]

    def write_column(self, table: str, column: str, values: Sequence[object]) -> None:
        """Replace ``main.table`` by its BASE copy with ``column`` set to ``values`` (by rowid)."""
        sql_type = self._types[table][column]
        self.con.execute(
            f'CREATE OR REPLACE TABLE main."{table}" AS '
            f'SELECT b.* EXCLUDE (__rid) REPLACE (v.val AS "{column}") '
            f'FROM (SELECT *, rowid AS __rid FROM {BASE}."{table}") AS b '
            f"JOIN (SELECT unnest(?::{sql_type}[]) AS val, unnest(range(?)) AS rid) AS v "
            "ON b.__rid = v.rid ORDER BY b.__rid",
            [list(values), len(values)],
        )

    def write_order(self, table: str, order: Sequence[int]) -> None:
        """Replace ``main.table`` by its BASE rows, unchanged, in the order ``order`` (rowids)."""
        self.con.execute(
            f'CREATE OR REPLACE TABLE main."{table}" AS '
            "SELECT b.* EXCLUDE (__rid) "
            f'FROM (SELECT *, rowid AS __rid FROM {BASE}."{table}") AS b '
            "JOIN (SELECT unnest(?::BIGINT[]) AS rid, unnest(range(?)) AS k) AS p "
            "ON b.__rid = p.rid ORDER BY p.k",
            [list(order), len(order)],
        )

    def base_fingerprints(self) -> dict[str, Fingerprint]:
        return {
            t: self.table_fingerprint(t, BASE) for t in [*self.corpus.seeds, *self.corpus.models]
        }

    def close(self) -> None:
        self.con.close()


@contextmanager
def compiled(corpus_dir: Path) -> Iterator[Corpus]:
    """Compile ``corpus_dir`` in a temp dir that lives for the ``with`` block."""
    with tempfile.TemporaryDirectory(prefix="dlens-oracle-") as tmp:
        yield compile_corpus(corpus_dir, Path(tmp))
