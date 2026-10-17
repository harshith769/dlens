"""Chunker: model SQL at CTE boundaries, column cards, doc chunks (retrieval-design.md).

Two rules shape everything here:

* **Indexed text comes only from project files.** ``Chunk.title`` and ``Chunk.text`` (what BM25
  and the embedder see) are built from SQL, YAML, docs blocks, exposures and README text. Graph
  facts (direct inputs, downstream counts) go to ``Chunk.meta`` only; S1 reuses this index and
  must never see parser output.
* **Only files the manifest names are read** (node ``original_file_path``, ``patch_path`` YAML,
  docs-block and exposure files), plus the project-root ``README.md``. Nothing is globbed, so
  gold and eval files next to the project (``lineage_spec.yml``, ``DESIGN.md``...) can't leak in.

Line numbers use the source ``.sql`` (the lineage citation basis). Without the project files
(artifact-only ingest outside a dbt project) model chunks use the compiled SQL and say so with
``line_basis="compiled"``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import sqlglot
from sqlglot import exp

from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import Message
from dlens.graph import LineageGraph
from dlens.lineage import column_id
from dlens.lineage.provenance import locate

CHUNKER_VERSION = 1
MAX_CHUNK_TOKENS = 300  # estimate_tokens (the LLMClient counter), title + text
WINDOW_LINES = 40  # fallback window for a model whose CTEs can't be found in the source

Kind = Literal["model", "column", "doc"]
LineBasis = Literal["source", "compiled"]
Level = Literal["line", "model"]


@dataclass(frozen=True)
class Chunk:
    id: str
    kind: Kind
    doc_kind: str | None
    model: str | None  # manifest unique_id of the node (model/seed/source/exposure/doc)
    column: str | None  # graph-style column id for cards
    file: str  # relative to the project dir (source basis) or the target dir (compiled basis)
    line_start: int
    line_end: int
    line_basis: LineBasis
    level: Level
    title: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)  # NOT indexed (graph facts live here)

    @property
    def indexed_text(self) -> str:
        """The only text BM25 and the embedder see."""
        return f"{self.title}\n{self.text}"

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Chunk:
        return cls(**d)


def chunk_id(kind: str, file: str, basis: str, a: int, b: int, title: str, text: str) -> str:
    key = "|".join((kind, file, basis, str(a), str(b), title, text))
    return "c_" + hashlib.sha1(key.encode()).hexdigest()[:8]


def est_tokens(text: str) -> int:
    return estimate_tokens([Message(role="tool", content=text)])


def fits_estimate(text: str) -> bool:
    return est_tokens(text) <= MAX_CHUNK_TOKENS


@dataclass
class ChunkSet:
    chunks: list[Chunk]
    files: dict[str, str]  # chunked file -> sha256 (part of the index key)
    stats: dict[str, Any]


# -- splitting ---------------------------------------------------------------------------------


def _word_pieces(line: str, fits: Callable[[str], bool], title: str) -> list[str]:
    """Split one over-long line at spaces (or hard, as a last resort) into pieces that fit."""
    out: list[str] = []
    cur = ""
    for word in re.split(r"(?<=\s)", line):
        cand = cur + word
        if cur and not fits(f"{title}\n{cand}"):
            out.append(cur)
            cur = word
        else:
            cur = cand
        while not fits(f"{title}\n{cur}") and len(cur) > 1:
            cut = len(cur) // 2
            while cut > 1 and not fits(f"{title}\n{cur[:cut]}"):
                cut //= 2
            out.append(cur[:cut])
            cur = cur[cut:]
    if cur:
        out.append(cur)
    return out


def split_lines(
    lines: list[str], first: int, title: str, fits: Callable[[str], bool]
) -> Iterator[tuple[int, int, str, bool]]:
    """Consecutive line windows (start, end, text, intra_line) that each fit, 1-based lines.

    A single line too long to fit on its own is split inside the line; its pieces keep that
    line's number (``intra_line=True``)."""
    title = f"{title} (part 999)"  # room for the suffix the caller adds
    cur: list[str] = []
    start = first
    for i, line in enumerate(lines):
        n = first + i
        if cur and not fits(f"{title}\n" + "\n".join([*cur, line])):
            yield start, n - 1, "\n".join(cur), False
            cur = []
        if not cur:
            start = n
            if not fits(f"{title}\n{line}"):
                for piece in _word_pieces(line, fits, title):
                    yield n, n, piece, True
                continue
        cur.append(line)
    if cur:
        yield start, first + len(lines) - 1, "\n".join(cur), False


def split_chunk(c: Chunk, fits: Callable[[str], bool]) -> list[Chunk]:
    """``c`` itself if it fits, else consecutive parts that each fit, titled ``(part k)``.

    When the text is the file's lines one-to-one (model SQL, docs blocks, README), each part
    cites its own lines. Otherwise (a card or description built from YAML values) every part
    keeps the chunk's citation. Raises if a part still can't fit (no silent truncation)."""
    if fits(c.indexed_text):
        return [c]
    lines = c.text.splitlines() or [c.text]
    one_to_one = c.line_end - c.line_start + 1 == len(lines)
    out: list[Chunk] = []
    for k, (a, b, text, intra) in enumerate(split_lines(lines, c.line_start, c.title, fits), 1):
        title = f"{c.title} (part {k})"
        if not fits(f"{title}\n{text}"):
            raise ValueError(f"chunk {c.id} can't be split to fit: {c.file}:{a}")
        if not one_to_one:
            a, b = c.line_start, c.line_end
        meta = {**c.meta, "split_intra_line": True} if intra else c.meta
        out.append(
            _make(
                c.kind,
                c.doc_kind,
                c.model,
                c.column,
                c.file,
                a,
                b,
                c.line_basis,
                c.level,
                title,
                text,
                meta,
            )
        )
    return out


def refit(chunks: list[Chunk], fits: Callable[[str], bool]) -> tuple[list[Chunk], int]:
    """Re-split every chunk whose indexed text doesn't fit (the real tokenizer's limit, at
    index build). Returns the new list (sorted by id) and how many chunks had to be split."""
    out: list[Chunk] = []
    n_split = 0
    for c in chunks:
        parts = split_chunk(c, fits)
        n_split += len(parts) > 1
        out += parts
    return sorted(out, key=lambda c: c.id), n_split


def _make(
    kind: Kind,
    doc_kind: str | None,
    model: str | None,
    column: str | None,
    file: str,
    a: int,
    b: int,
    basis: LineBasis,
    level: Level,
    title: str,
    text: str,
    meta: dict[str, Any] | None = None,
) -> Chunk:
    return Chunk(
        id=chunk_id(kind, file, basis, a, b, title, text),
        kind=kind,
        doc_kind=doc_kind,
        model=model,
        column=column,
        file=file,
        line_start=a,
        line_end=b,
        line_basis=basis,
        level=level,
        title=title,
        text=text,
        meta=dict(meta or {}),
    )


# -- SQL: CTE boundaries -----------------------------------------------------------------------


def _skip(text: str, i: int) -> int:
    """End of an opaque span (string, comment, Jinja) starting at ``i``, else ``i``."""
    for start, end in (("{{", "}}"), ("{%", "%}"), ("{#", "#}"), ("/*", "*/")):
        if text.startswith(start, i):
            j = text.find(end, i + 2)
            return len(text) if j < 0 else j + len(end)
    if text.startswith("--", i):
        j = text.find("\n", i)
        return len(text) if j < 0 else j
    if text[i] in "'\"`":
        j = text.find(text[i], i + 1)
        return len(text) if j < 0 else j + 1
    return i


def _depth0_select(text: str, start: int) -> int | None:
    """Offset of the first ``select`` at parenthesis depth 0 at or after ``start``, skipping
    strings, comments and Jinja; None if there is none."""
    depth = 0
    i = start
    while i < len(text):
        j = _skip(text, i)
        if j != i:
            i = j
            continue
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and text[i : i + 6].lower() == "select":
            before = text[i - 1] if i else " "
            after = text[i + 6] if i + 6 < len(text) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return i
        i += 1
    return None


def _body_end(text: str, start: int) -> int:
    """Offset just past the parenthesised body of the CTE whose name starts at ``start``."""
    i = text.find("(", start)
    if i < 0:
        return start
    depth = 0
    while i < len(text):
        j = _skip(text, i)
        if j != i:
            i = j
            continue
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def cte_names(compiled: str, dialect: str) -> list[str]:
    """CTE aliases of the outermost WITH of the compiled SQL, in order (sqlglot; [] on failure)."""
    try:
        tree = sqlglot.parse_one(compiled, dialect=dialect)
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError, ValueError):
        return []
    with_ = (tree.args.get("with_") or tree.args.get("with")) if tree is not None else None
    if not isinstance(with_, exp.With):
        return []
    return [cte.alias for cte in with_.expressions if cte.alias]


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def cte_segments(text: str, names: list[str]) -> list[tuple[int, int, str]] | None:
    """(first_line, last_line, label) per CTE plus the final select, or None if a name isn't
    found in order (the caller falls back to line windows)."""
    if not names:
        return None
    starts: list[int] = []
    pos = 0
    for name in names:
        m = re.compile(
            rf"^[ \t]*(?:with[ \t]+)?,?[ \t]*{re.escape(name)}[ \t]+as[ \t]*\(",
            re.IGNORECASE | re.MULTILINE,
        ).search(text, pos)
        if m is None:
            return None
        starts.append(m.start())
        pos = m.end()
    final = _depth0_select(text, _body_end(text, starts[-1]))
    total = _line_of(text, len(text.rstrip("\n")))
    lines = [_line_of(text, s) for s in starts]
    lines[0] = 1  # header (config block, comments, ``with``) goes with the first CTE
    segs: list[tuple[int, int, str]] = []
    final_line = _line_of(text, final) if final is not None else None
    bounds = [*lines, final_line if final_line is not None else total + 1]
    for k, name in enumerate(names):
        a, b = bounds[k], bounds[k + 1] - 1
        if b >= a:
            segs.append((a, b, f"cte {name}"))
    if final_line is not None:
        segs.append((final_line, total, "final select"))
    return segs


# -- YAML / docs locators ----------------------------------------------------------------------


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _entry(lines: list[str], name: str, lo: int = 0, hi: int | None = None) -> tuple[int, int]:
    """0-based (first, last) line of the YAML list entry ``- name: <name>`` within lo..hi."""
    hi = len(lines) if hi is None else hi
    pat = re.compile(rf"^\s*-\s*name:\s*['\"]?{re.escape(name)}['\"]?\s*(#.*)?$", re.IGNORECASE)
    for i in range(lo, hi):
        if pat.match(lines[i]):
            dash = _indent(lines[i])
            j = i + 1
            while j < hi and (not lines[j].strip() or _indent(lines[j]) > dash):
                j += 1
            while j - 1 > i and not lines[j - 1].strip():
                j -= 1
            return i, j - 1
    return -1, -1


def _key_block(lines: list[str], key: str, lo: int, hi: int, indent: int) -> tuple[int, int]:
    """0-based (first, last) line of ``key:`` at exactly ``indent`` within lo..hi, including a
    block scalar or continuation lines (more indented than the key)."""
    for i in range(lo, hi + 1):
        line = lines[i]
        if _indent(line) == indent and line.strip().startswith(f"{key}:"):
            j = i + 1
            while j <= hi and (not lines[j].strip() or _indent(lines[j]) > indent):
                j += 1
            while j - 1 > i and not lines[j - 1].strip():
                j -= 1
            return i, j - 1
    return -1, -1


def yaml_description(
    text: str, section: str, entry: str, column: str | None = None, table: str | None = None
) -> tuple[int, int] | None:
    """1-based lines of a ``description:`` in schema YAML: the entry's own, or a column's.
    ``table`` is the source table for sources (``sources: - name: <source> tables: - name:``)."""
    lines = text.splitlines()
    sec = next((i for i, ln in enumerate(lines) if ln.rstrip() == f"{section}:"), -1)
    if sec < 0:
        return None
    a, b = _entry(lines, entry, sec + 1)
    if a < 0:
        return None
    if table is not None:
        a, b = _entry(lines, table, a + 1, b + 1)
        if a < 0:
            return None
    if column is not None:
        a, b = _entry(lines, column, a + 1, b + 1)
        if a < 0:
            return None
    s, e = _key_block(lines, "description", a, b, _indent(lines[a]) + 2)
    if s < 0:
        # ``- name: x`` may be followed on the same dash: description is then at dash + 2.
        return None
    return s + 1, e + 1


def yaml_entry_lines(text: str, section: str, entry: str) -> tuple[int, int] | None:
    lines = text.splitlines()
    sec = next((i for i, ln in enumerate(lines) if ln.rstrip() == f"{section}:"), -1)
    if sec < 0:
        return None
    a, b = _entry(lines, entry, sec + 1)
    return None if a < 0 else (a + 1, b + 1)


_DOC_REF = re.compile(r"""doc\(\s*['"]([\w.]+)['"]\s*\)""")


def docs_block_lines(text: str, name: str) -> tuple[int, int] | None:
    """1-based lines from ``{% docs name %}`` to ``{% enddocs %}``."""
    m = re.search(rf"\{{%-?\s*docs\s+{re.escape(name)}\s*-?%\}}", text)
    if m is None:
        return None
    e = re.compile(r"\{%-?\s*enddocs\s*-?%\}").search(text, m.end())
    end = e.end() if e else len(text)
    return _line_of(text, m.start()), _line_of(text, end)


# -- project files -----------------------------------------------------------------------------


def _safe_rel(rel: str) -> bool:
    p = PurePosixPath(rel)
    return bool(rel) and not p.is_absolute() and ".." not in p.parts


@dataclass
class _Files:
    """Reads only manifest-referenced files, relative to their package root."""

    project_dir: Path | None
    root_name: str
    packages_dir: str
    read_log: dict[str, str] = field(default_factory=dict)  # display path -> sha256

    def display(self, package: str, rel: str) -> str:
        if package == self.root_name:
            return rel
        return f"{self.packages_dir}/{package}/{rel}"

    def read(self, package: str, rel: str) -> tuple[str, str] | None:
        """(display path, text) of a project file, or None if unavailable."""
        if self.project_dir is None or not _safe_rel(rel):
            return None
        shown = self.display(package, rel)
        path = self.project_dir / shown
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        self.read_log[shown] = hashlib.sha256(text.encode()).hexdigest()
        return shown, text


def _packages_dir(project_dir: Path | None) -> str:
    if project_dir is None:
        return "dbt_packages"
    try:
        text = (project_dir / "dbt_project.yml").read_text(encoding="utf-8")
    except OSError:
        return "dbt_packages"
    m = re.search(r"^packages-install-path:\s*['\"]?([^'\"\s#]+)", text, re.MULTILINE)
    return m.group(1).strip("/") if m else "dbt_packages"


def _patch_rel(patch_path: str | None) -> tuple[str | None, str | None]:
    """``pkg://models/schema.yml`` -> (pkg, models/schema.yml)."""
    if not patch_path or "://" not in patch_path:
        return None, None
    pkg, rel = patch_path.split("://", 1)
    return pkg, rel


# -- the chunker -------------------------------------------------------------------------------


@dataclass
class _Ctx:
    graph: LineageGraph
    manifest: dict[str, Any]
    catalog: dict[str, Any] | None
    files: _Files
    target_dir: Path
    dialect: str
    fits: Callable[[str], bool]
    chunks: list[Chunk] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def bump(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def add(
        self,
        kind: Kind,
        doc_kind: str | None,
        model: str | None,
        column: str | None,
        file: str,
        a: int,
        b: int,
        basis: LineBasis,
        level: Level,
        title: str,
        text: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        if not text.strip():
            return
        chunk = _make(kind, doc_kind, model, column, file, a, b, basis, level, title, text, meta)
        parts = split_chunk(chunk, self.fits)
        if len(parts) > 1:
            self.bump("split_for_size")
            self.bump("split_intra_line", sum(bool(p.meta.get("split_intra_line")) for p in parts))
        self.chunks += parts

    def docs_block(self, name: str, package: str | None) -> dict[str, Any] | None:
        docs = self.manifest.get("docs", {})
        for uid in (f"doc.{package}.{name}", *sorted(docs)):
            d = docs.get(uid)
            if d and d.get("name") == name and d.get("package_name") != "dbt":
                return dict(d)
        return None

    def cite_description(
        self,
        package: str,
        yml_rel: str | None,
        section: str,
        entry: str,
        column: str | None = None,
        table: str | None = None,
    ) -> tuple[str, int, int, Level] | None:
        """Where a description's words are: its YAML lines, or the docs block it renders."""
        if yml_rel is None:
            return None
        got = self.files.read(package, yml_rel)
        if got is None:  # no project files: name the YAML file, claim no lines
            return self.files.display(package, yml_rel), 1, 1, "model"
        shown, text = got
        span = yaml_description(text, section, entry, column, table)
        if span is None:
            return shown, 1, max(1, text.count("\n") + 1), "model"
        raw = "\n".join(text.splitlines()[span[0] - 1 : span[1]])
        ref = _DOC_REF.search(raw)
        if ref:
            blk = self.docs_block(ref.group(1).split(".")[-1], package)
            if blk:
                got_md = self.files.read(blk["package_name"], blk["original_file_path"])
                if got_md:
                    md_shown, md = got_md
                    lines = docs_block_lines(md, blk["name"])
                    if lines:
                        return md_shown, lines[0], lines[1], "line"
        return shown, span[0], span[1], "line"


def _node_title(node: dict[str, Any]) -> str:
    if node["resource_type"] == "source":
        return f"{node['source_name']}.{node['name']}"
    return str(node["name"])


def _compiled(ctx: _Ctx, node: dict[str, Any]) -> str:
    """A model's compiled SQL: ``compiled_code``, else ``target/compiled/<pkg>/<path>``."""
    compiled = node.get("compiled_code") or ""
    rel = node.get("original_file_path") or ""
    if not compiled and _safe_rel(rel):
        cpath = ctx.target_dir / "compiled" / node["package_name"] / rel
        if cpath.is_file():
            compiled = cpath.read_text(encoding="utf-8", errors="replace")
    return compiled


def _model_chunks(ctx: _Ctx, node: dict[str, Any]) -> None:
    uid, pkg, rel = node["unique_id"], node["package_name"], node.get("original_file_path") or ""
    compiled = _compiled(ctx, node)
    got = ctx.files.read(pkg, rel) if rel.endswith(".sql") else None
    basis: LineBasis
    if got is not None:
        shown, text, basis = got[0], got[1], "source"
        names = [n for n in cte_names(compiled, ctx.dialect) if not n.startswith("__dbt__cte__")]
    elif compiled:
        shown, text, basis = f"compiled/{pkg}/{rel}", compiled, "compiled"
        names = cte_names(compiled, ctx.dialect)
    else:
        ctx.bump("models_without_sql")
        return
    lines = text.splitlines()
    segs = cte_segments(text, names)
    if segs is None:
        ctx.bump("models_window_fallback" if names else "models_without_ctes")
        segs = [
            (
                a,
                min(a + WINDOW_LINES - 1, len(lines)),
                f"lines {a}-{min(a + WINDOW_LINES - 1, len(lines))}",
            )
            for a in range(1, len(lines) + 1, WINDOW_LINES)
        ]
    else:
        ctx.bump("models_cte_split")
    for a, b, label in segs:
        body = "\n".join(lines[a - 1 : b])
        ctx.add(
            "model",
            None,
            uid,
            None,
            shown,
            a,
            b,
            basis,
            "line",
            f"{node['name']} · {label}",
            body,
        )


def _yaml_columns(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c.lower(): dict(v, name=v.get("name") or c) for c, v in node.get("columns", {}).items()}


def _catalog_columns(ctx: _Ctx, uid: str) -> dict[str, dict[str, Any]]:
    if ctx.catalog is None:
        return {}
    entry = ctx.catalog.get("nodes", {}).get(uid) or ctx.catalog.get("sources", {}).get(uid) or {}
    return {
        c.lower(): dict(v, name=v.get("name") or c) for c, v in entry.get("columns", {}).items()
    }


def _graph_meta(graph: LineageGraph, cid: str) -> dict[str, Any]:
    if not graph.has_column(cid):
        return {"column_id": cid, "in_graph": False}
    nx = graph.nx_graph
    return {
        "column_id": cid,
        "in_graph": True,
        "direct_inputs": int(nx.in_degree(cid)),
        "downstream": len(graph.downstream(cid, include_indirect=False).via),
    }


def _cards(ctx: _Ctx, node: dict[str, Any], carded: set[str]) -> None:
    uid, pkg = node["unique_id"], node["package_name"]
    yml = _yaml_columns(node)
    cat = _catalog_columns(ctx, uid)
    title_base = _node_title(node)
    rtype = node["resource_type"]
    yml_pkg, yml_rel = _patch_rel(node.get("patch_path"))
    if rtype == "source":
        yml_pkg, yml_rel = pkg, node.get("original_file_path")
    src = None
    rel = node.get("original_file_path") or ""
    if rtype == "model" and rel.endswith(".sql"):
        src = ctx.files.read(pkg, rel)
    for key in sorted(set(yml) | set(cat)):
        y, c = yml.get(key, {}), cat.get(key, {})
        name = y.get("name") or c.get("name") or key
        dtype = c.get("type") or y.get("data_type") or ""
        desc = (y.get("description") or "").strip()
        cid = column_id(uid, name)
        carded.add(cid)
        text = f"{title_base}.{name}"
        if dtype:
            text += f"\ntype: {dtype}"
        if desc:
            text += f"\ndescription: {desc}"
        cite: tuple[str, int, int, Level] | None = None
        basis: LineBasis = "source"
        if y:
            if rtype == "source":
                cite = ctx.cite_description(
                    yml_pkg or pkg,
                    yml_rel,
                    "sources",
                    node["source_name"],
                    name,
                    table=node["name"],
                )
            else:
                section = {"model": "models", "seed": "seeds", "snapshot": "snapshots"}.get(
                    rtype, "models"
                )
                cite = ctx.cite_description(yml_pkg or pkg, yml_rel, section, node["name"], name)
            if cite and not desc:
                cite = None  # no description: cite the column in SQL instead, if possible
        if cite is None and src is not None:
            loc = locate(src[1], name)
            if not loc.model_level:
                cite = (src[0], loc.lines[0], loc.lines[1], "line")
            else:
                cite = (src[0], 1, max(1, src[1].count("\n") + 1), "model")
        if cite is None and rtype == "model" and ctx.files.project_dir is None:
            compiled = _compiled(ctx, node)
            if compiled:  # no project files: locate the column in the compiled SQL
                basis = "compiled"
                loc = locate(compiled, name)
                shown = f"compiled/{pkg}/{rel}"
                if not loc.model_level:
                    cite = (shown, loc.lines[0], loc.lines[1], "line")
                else:
                    cite = (shown, 1, max(1, compiled.count("\n") + 1), "model")
        if cite is None:
            got = ctx.files.read(pkg, rel) if rel else None
            if got is not None:
                cite = (got[0], 1, max(1, got[1].count("\n") + 1), "model")
            else:  # nothing readable: name the file, claim no lines
                cite = (ctx.files.display(pkg, rel) if rel else uid, 1, 1, "model")
        meta = {**_graph_meta(ctx.graph, cid), "in_yaml": bool(y), "in_catalog": bool(c)}
        assert cite is not None
        file, a, b, level = cite
        ctx.add(
            "column",
            "column_description" if desc else None,
            uid,
            cid,
            file,
            a,
            b,
            basis,
            level,
            f"{title_base}.{name} · column",
            text,
            meta,
        )
        ctx.bump("cards")


def _node_description(ctx: _Ctx, node: dict[str, Any]) -> None:
    desc = (node.get("description") or "").strip()
    if not desc:
        return
    rtype, pkg = node["resource_type"], node["package_name"]
    if rtype == "source":
        cite = ctx.cite_description(
            pkg, node.get("original_file_path"), "sources", node["source_name"], table=node["name"]
        )
        doc_kind = "source_description"
    else:
        yml_pkg, yml_rel = _patch_rel(node.get("patch_path"))
        section = {"model": "models", "seed": "seeds", "snapshot": "snapshots"}.get(rtype, "models")
        cite = ctx.cite_description(yml_pkg or pkg, yml_rel, section, node["name"])
        doc_kind = "model_description"
    if cite is None:
        return
    file, a, b, level = cite
    ctx.add(
        "doc",
        doc_kind,
        node["unique_id"],
        None,
        file,
        a,
        b,
        "source",
        level,
        f"{_node_title(node)} · description",
        desc,
    )


def _exposure(ctx: _Ctx, x: dict[str, Any]) -> None:
    got = ctx.files.read(x["package_name"], x.get("original_file_path") or "")
    if got is None:
        return
    shown, text = got
    span = yaml_entry_lines(text, "exposures", x["name"])
    a, b, level = (*span, "line") if span else (1, max(1, text.count("\n") + 1), "model")
    owner = (x.get("owner") or {}).get("name") or ""
    body = f"exposure {x['name']} ({x.get('type', '')})"
    if x.get("label"):
        body += f"\nlabel: {x['label']}"
    if (x.get("description") or "").strip():
        body += f"\ndescription: {x['description'].strip()}"
    if owner:
        body += f"\nowner: {owner}"
    ctx.add(
        "doc",
        "exposure",
        x["unique_id"],
        None,
        shown,
        a,
        b,
        "source",
        level,  # type: ignore[arg-type]
        f"{x['name']} · exposure",
        body,
    )


def _docs_blocks(ctx: _Ctx) -> None:
    for uid, d in sorted(ctx.manifest.get("docs", {}).items()):
        if d.get("package_name") == "dbt":
            continue
        got = ctx.files.read(d["package_name"], d.get("original_file_path") or "")
        if got is None:
            continue
        shown, text = got
        span = docs_block_lines(text, d["name"])
        if span is None:
            continue
        a, b = span
        lines = text.splitlines()[a - 1 : b]
        ctx.add(
            "doc",
            "docs_block",
            uid,
            None,
            shown,
            a,
            b,
            "source",
            "line",
            f"{d['name']} · docs block",
            "\n".join(lines),
        )


def _readme(ctx: _Ctx) -> None:
    if ctx.files.project_dir is None:
        return
    got = ctx.files.read(ctx.files.root_name, "README.md")
    if got is None:
        return
    shown, text = got
    lines = text.splitlines()
    heads = [i for i, ln in enumerate(lines) if re.match(r"^#{1,6}\s", ln)] or [0]
    if heads[0] != 0:
        heads = [0, *heads]
    for k, h in enumerate(heads):
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        section = lines[h:end]
        while section and not section[-1].strip():
            section.pop()
            end -= 1
        if not section:
            continue
        head = section[0].lstrip("#").strip() if section[0].startswith("#") else "README"
        ctx.add(
            "doc",
            "readme",
            None,
            None,
            shown,
            h + 1,
            end,
            "source",
            "line",
            f"README · {head}",
            "\n".join(section),
        )


def _parser_only(ctx: _Ctx, carded: set[str]) -> None:
    eph = {
        uid
        for uid, n in ctx.manifest["nodes"].items()
        if (n.get("config") or {}).get("materialized") == "ephemeral"
    }
    e = g = o = 0
    for cid in ctx.graph.columns():
        if cid in carded:
            continue
        model = ctx.graph.model_of(cid)
        if model in eph:
            e += 1
        elif ctx.catalog is None:
            g += 1
        else:
            o += 1
    ctx.stats["parser_only_ephemeral"] = e
    ctx.stats["parser_only_schema_growth"] = g
    ctx.stats["parser_only_not_in_catalog"] = o


def build_chunks(
    graph: LineageGraph,
    target_dir: Path,
    project_dir: Path | None,
    dialect: str = "duckdb",
    fits: Callable[[str], bool] = fits_estimate,
) -> ChunkSet:
    """All chunks of a project. ``project_dir`` None means no source files (compiled basis).
    ``catalog.json`` is read from ``target_dir`` only if it exists (a real warehouse catalog)."""
    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    cat_path = target_dir / "catalog.json"
    catalog = json.loads(cat_path.read_text(encoding="utf-8")) if cat_path.is_file() else None
    root = manifest.get("metadata", {}).get("project_name") or ""
    files = _Files(project_dir, root, _packages_dir(project_dir))
    ctx = _Ctx(graph, manifest, catalog, files, target_dir, dialect, fits)
    nodes = {**manifest["nodes"], **manifest.get("sources", {})}
    carded: set[str] = set()
    for uid in sorted(nodes):
        node = nodes[uid]
        rtype = node.get("resource_type")
        if rtype not in ("model", "seed", "source", "snapshot"):
            continue
        if rtype == "model":
            _model_chunks(ctx, node)
        _cards(ctx, node, carded)
        _node_description(ctx, node)
    for _uid, x in sorted(manifest.get("exposures", {}).items()):
        _exposure(ctx, x)
    _docs_blocks(ctx)
    _readme(ctx)
    _parser_only(ctx, carded)
    chunks = sorted(ctx.chunks, key=lambda c: c.id)
    seen: dict[str, Chunk] = {}
    for c in chunks:
        other = seen.get(c.id)
        if other is not None and other != c:
            raise ValueError(f"chunk id collision {c.id}")
        seen[c.id] = c
    chunks = list(seen.values())
    stats = dict(sorted(ctx.stats.items()))
    stats["chunks"] = len(chunks)
    for kind in ("model", "column", "doc"):
        stats[f"chunks_{kind}"] = sum(c.kind == kind for c in chunks)
    stats["line_basis"] = {
        b: sum(c.line_basis == b for c in chunks) for b in ("source", "compiled")
    }
    stats["max_est_tokens"] = max((est_tokens(c.indexed_text) for c in chunks), default=0)
    return ChunkSet(chunks, dict(sorted(files.read_log.items())), stats)
