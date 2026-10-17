"""resolve_entity (linker v2, S08): free text -> ranked candidate columns and models.

Design: docs/plans/linker-design.md (owner-approved, with amendments A-C). Three stages:

1. **exact** (always ranked first): a full id, a ``model.column`` id or a model name (1.00); a
   literal column name (0.97, every column with that name).
2. **normalised**: ``surface`` (case, separators, camelCase; 0.93), ``rewritten`` (plural, the
   abbreviation table, phrase rules, weak ``usd``, word order; 0.87), ``fuzzy`` (bounded token
   similarity, <= 0.80). Plus a model-named-in-the-text bonus (+0.06 x coverage) and a layer
   prior (marts +0.010 ... raw -0.005).
3. **hybrid** over the S07 column cards, only when stage 2 found no surface/rewritten match and
   the toolbox has a search index: candidates need dense cosine >= COS_MIN; score
   0.50 + 0.30 x rrf_norm. Ranked together with the stage-2 fuzzy candidates.

Below NO_MATCH (tau) nothing is a candidate. ``ambiguous`` is ``top1 - top2 < AMBIGUOUS_GAP``
(delta, unchanged; the agent loop imports it). Weights are set by reasoning, never fitted.

Dotted ``model.column`` text (amendment C) never gets stage 2/3 rescue: it is exact, or it maps
through the abbreviation table alone to exactly one column of that model (``dotted_column``, the
one function the agent loop's unknown-column refusal also uses), or it is no-match.

The payload keeps the v1 shape (ADR 0022: ``match`` may be ``hybrid``; optional ``hybrid`` key).
Score parts and ``closest`` go to the side record only: the LLM never sees below-threshold ids.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from dlens.agent.tools.common import ToolOutput, as_int, as_str
from dlens.agent.tools.provenance import Provenance
from dlens.graph import LineageGraph
from dlens.lineage import column_id

if TYPE_CHECKING:
    from dlens.retrieval.index import SearchIndex

# Design §2.1 (owner-approved): abbreviation -> canonical token, applied to both sides.
ABBREVIATIONS = {
    "amt": "amount",
    "qty": "quantity",
    "cust": "customer",
    "prod": "product",
    "num": "number",
    "ts": "timestamp",
    "dt": "date",
    "desc": "description",
    "cat": "category",
    "addr": "address",
    "pmt": "payment",
    "txn": "transaction",
    "avg": "average",
    "tot": "total",
    "pct": "percent",
    "percentage": "percent",
    "promo": "promotion",
    "rev": "revenue",
}
WEAK_TOKENS = {"usd"}  # ignored only in the rewritten tier ("payment amount" ~ amount_usd)
LAYER_TOKENS = {"raw", "stg", "int", "fct", "dim"}  # model-name prefixes (amendment B)
# Design §2.3: dropped from the text only, and only when the column name doesn't contain them.
STOPWORDS = set(
    "the a an of per by for on in from at to with each all what which is are does do how where "
    "when why column field".split()
)
PHRASE_BOUNDARY = {"per", "by", "for", "on", "in", "of", "from"}

EXACT_ID, EXACT_NAME = 1.00, 0.97
SURFACE, REWRITTEN, FUZZY_MAX = 0.93, 0.87, 0.80
MODEL_FUZZY = 0.9  # model-name fuzzy scores are 0.9 x the column bound, as in v1
HYBRID_BASE, HYBRID_SPAN = 0.50, 0.30
MODEL_BONUS = 0.06
LAYER_PRIOR = {"marts": 0.010, "intermediate": 0.005, "staging": 0.0, "raw": -0.005}
SCORE_CAP = 0.96  # printed scores of stages 2-3; ranking and ``ambiguous`` use the raw sum
NO_MATCH = 0.60  # tau
AMBIGUOUS_GAP = 0.05  # delta
COS_MIN = 0.80
HYBRID_K = 10
CLOSEST = 3
RRF_MAX = 2 / 61  # rank 1 in both lists, RRF k = 60

Tier = Literal[
    "exact_id", "exact_name", "dotted_abbreviation", "surface", "rewritten", "fuzzy", "hybrid"
]
_MATCH: dict[str, str] = {
    "exact_id": "exact",
    "exact_name": "exact",
    "dotted_abbreviation": "normalised",
    "surface": "normalised",
    "rewritten": "normalised",
    "fuzzy": "fuzzy",
    "hybrid": "hybrid",
}
_STAGE = {"exact_id": 1, "exact_name": 1, "hybrid": 3}


# -- normalisation ------------------------------------------------------------------------------


def split(text: str) -> list[str]:
    """Surface tokens: lower case, split on non-alphanumerics and camelCase."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return [t.lower() for t in re.split(r"[^A-Za-z0-9]+", spaced) if t]


def singular(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def rewrite(t: str) -> str:
    """A surface token's rewritten form: plural stripped (amendment A), then abbreviation."""
    t = singular(t)
    return ABBREVIATIONS.get(t, t)


def tokens(text: str) -> list[str]:
    """Rewritten tokens of a name or text (v1 helper name, kept for callers)."""
    return [rewrite(t) for t in split(text)]


def core(toks: list[str]) -> list[str]:
    """Without weak tokens (unless that would leave nothing)."""
    kept = [t for t in toks if t not in WEAK_TOKENS]
    return kept or toks


def abbreviated(text: str) -> list[str]:
    """The abbreviation table alone (no plural): the only rewrite a dotted id may use."""
    return [ABBREVIATIONS.get(t, t) for t in split(text)]


def model_body(name: str) -> list[str]:
    """Rewritten model-name tokens without layer prefixes (amendment B)."""
    toks = tokens(name)
    while toks and toks[0] in LAYER_TOKENS:
        toks = toks[1:]
    return toks


@dataclass(frozen=True)
class Form:
    """One reading of the text: surface tokens, and the phrase rule that made it (if any)."""

    surface: tuple[str, ...]
    rule: str | None = None


_PHRASES = (("P1", ("number", "of"), "count"), ("P2", ("how", "many"), "count"),
            ("P3", ("count", "of"), "count"), ("P4", ("total",), "total"))  # fmt: skip


def forms(text: str) -> list[Form]:
    """The text itself plus one extra form per phrase rule that applies (design §2.2)."""
    toks = split(text)
    out = [Form(tuple(toks))]
    for rule, head, tail in _PHRASES:
        n = len(head)
        for i in range(len(toks) - n + 1):
            if tuple(toks[i : i + n]) != head:
                continue
            j = i + n
            while j < len(toks) and toks[j] not in PHRASE_BOUNDARY:
                j += 1
            x = toks[i + n : j]
            if x:
                out.append(Form(tuple(toks[:i] + x + [tail] + toks[j:]), rule))
            break
    return out


# -- scoring ------------------------------------------------------------------------------------


def _soft_dice(a: list[str], b: list[str]) -> float:
    """Token overlap in [0, 1]: each token of ``b`` is used at most once (greedy, best first),
    a pair counts if its difflib ratio is >= 0.8. Bounded, unlike v1 (the >1.0 bug)."""
    if not a or not b:
        return 0.0
    pairs = sorted(
        ((difflib.SequenceMatcher(None, x, y).ratio(), i, j) for i, x in enumerate(a)
         for j, y in enumerate(b)),
        reverse=True,
    )  # fmt: skip
    used_a: set[int] = set()
    used_b: set[int] = set()
    total = 0.0
    for r, i, j in pairs:
        if r < 0.8:
            break
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        total += r
    return 2 * total / (len(a) + len(b))


def fuzzy(q: list[str], c: list[str]) -> float:
    """Name similarity in [0, FUZZY_MAX]: 0.7 token overlap + 0.3 character shape."""
    seq = difflib.SequenceMatcher(None, " ".join(q), " ".join(c)).ratio()
    return FUZZY_MAX * (0.7 * _soft_dice(q, c) + 0.3 * seq)


def layer(name: str, resource_type: str) -> str | None:
    if resource_type == "seed" or name.startswith("raw_"):
        return "raw"
    prefix = name.split("_", 1)[0]
    return {"stg": "staging", "int": "intermediate", "fct": "marts", "dim": "marts"}.get(prefix)


@dataclass
class Cand:
    """One candidate with its score parts (the side record's ``parts``)."""

    cid: str
    row: dict[str, str]
    tier: Tier
    base: float
    model_bonus: float = 0.0
    layer: float = 0.0
    seed: int = 0
    rules: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def stage(self) -> int:
        return _STAGE.get(self.tier, 2)

    @property
    def raw(self) -> float:
        return self.base + self.model_bonus + self.layer

    @property
    def score(self) -> float:
        return self.raw if self.stage == 1 else min(self.raw, SCORE_CAP)

    def parts(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "tier": self.tier,
            "base": round(self.base, 4),
            "model_bonus": round(self.model_bonus, 4),
            "layer": self.layer,
            "raw": round(self.raw, 4),
            "rules": self.rules,
            **self.extra,
        }


def _match(
    form: Form, col_surface: list[str], body: list[str]
) -> tuple[Tier, float, list[str], float]:
    """Best stage-2 tier of one text form against one column (design §2, §3.1).

    Returns (tier, base, rules, coverage). Text tokens that name the column's model (and are not
    part of the column name) are context: they give the model bonus and leave the matching side.
    Stopwords and layer tokens leave it too, unless the column name contains them."""
    col_rw = [rewrite(t) for t in col_surface]
    col_set = set(col_surface) | set(col_rw)
    ctx = {rewrite(t) for t in form.surface if rewrite(t) in body and rewrite(t) not in col_set}
    coverage = len(ctx) / len(body) if body else 0.0
    rest = [
        t
        for t in form.surface
        if t in col_set or (rewrite(t) not in ctx and t not in STOPWORDS and t not in LAYER_TOKENS)
    ]
    rules = [form.rule] if form.rule else []
    rest_rw = [rewrite(t) for t in rest]
    if rest == col_surface and not rules:
        return "surface", SURFACE, rules, coverage
    used = rules + _rewrites(rest, rest_rw, col_surface, col_rw)
    if rest_rw == col_rw or core(rest_rw) == core(col_rw):
        return "rewritten", REWRITTEN, used, coverage
    if sorted(rest_rw) == sorted(col_rw) or sorted(core(rest_rw)) == sorted(core(col_rw)):
        return "rewritten", REWRITTEN, [*used, "word_order"], coverage
    return "fuzzy", fuzzy(core(rest_rw), core(col_rw)), rules, coverage


def _rewrites(rest: list[str], rest_rw: list[str], col: list[str], col_rw: list[str]) -> list[str]:
    """Which rewrites a rewritten match used (for the score parts)."""
    out = sorted({t for t in [*rest, *col] if t in ABBREVIATIONS})
    if any(singular(t) != t for t in [*rest, *col]):
        out.append("plural")
    if core(rest_rw) != rest_rw or core(col_rw) != col_rw:
        out.append("weak_usd")
    return out


# -- dotted ids (amendment C; shared with the agent loop) ----------------------------------------


@dataclass(frozen=True)
class Dotted:
    """What a ``model.column`` text names: ``columns`` empty means no-match."""

    model_uids: tuple[str, ...]
    columns: tuple[str, ...]
    how: Literal["exact", "abbreviation", "none"]
    closest: tuple[str, ...] = ()


def model_uids_by_name(g: LineageGraph) -> dict[str, list[str]]:
    by_name: dict[str, list[str]] = {}
    for uid in g.model_ids():
        by_name.setdefault((g.model_info(uid) or {}).get("name", "").lower(), []).append(uid)
    return by_name


def dotted_column(
    g: LineageGraph, model: str, column: str, by_name: dict[str, list[str]] | None = None
) -> Dotted | None:
    """None if ``model`` names no model/seed/source. Otherwise the column exactly, or the columns
    of that model the column part maps to through the abbreviation table alone (incl. weak
    ``usd``), or none. Exactly one is a resolution; 2+ are ambiguous; 0 is no-match. No plural,
    fuzzy, typo, phrase or hybrid rescue. The agent loop refuses exactly when ``columns`` is
    empty, so the loop and the linker cannot disagree."""
    uids = (by_name if by_name is not None else model_uids_by_name(g)).get(model.lower())
    if not uids:
        return None
    col = column.lower()
    exact = tuple(column_id(u, col) for u in uids if g.has_column(column_id(u, col)))
    if exact:
        return Dotted(tuple(uids), exact, "exact")
    own = [c for c in g.columns() if g.model_of(c) in uids]
    want = abbreviated(col)
    hits = tuple(
        c
        for c in own
        if (have := abbreviated(g.nx_graph.nodes[c]["name"])) == want or core(have) == core(want)
    )
    if hits:
        return Dotted(tuple(uids), hits, "abbreviation")
    names = sorted({g.nx_graph.nodes[c]["name"] for c in own})
    close = difflib.get_close_matches(col, names, n=CLOSEST, cutoff=0.0)
    return Dotted(tuple(uids), (), "none", tuple(f"{model.lower()}.{n}" for n in close))


_DOTTED = re.compile(r"^\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*$")


# -- the tool -----------------------------------------------------------------------------------


def _col_row(g: LineageGraph, cid: str, tier: Tier) -> dict[str, str]:
    return {"id": g.display_name(cid), "kind": "column", "match": _MATCH[tier]}


def _layer_of(g: LineageGraph, cid: str) -> tuple[float, int]:
    info = g.model_info(g.model_of(cid)) or {}
    rtype = info.get("resource_type", "")
    lay = layer(info.get("name", ""), rtype)
    return (LAYER_PRIOR[lay] if lay else 0.0), int(rtype == "seed")


def _stage1(g: LineageGraph, low: str) -> list[Cand]:
    out: list[Cand] = []
    for cid in g.columns():
        node = g.nx_graph.nodes[cid]
        mname = (g.model_info(node["model"]) or {}).get("name", node["model"])
        if low in (cid, f"{mname}.{node['name']}".lower()):
            out.append(Cand(cid, _col_row(g, cid, "exact_id"), "exact_id", EXACT_ID))
        elif low == node["name"].lower():
            seed = _layer_of(g, cid)[1]
            out.append(
                Cand(cid, _col_row(g, cid, "exact_name"), "exact_name", EXACT_NAME, seed=seed)
            )
    for uid in g.model_ids():
        info = g.model_info(uid) or {}
        if info.get("resource_type") == "model" and low in (uid, info.get("name", "").lower()):
            row = {"id": info.get("name", uid), "kind": "model", "match": "exact"}
            out.append(Cand(uid, row, "exact_id", EXACT_ID))
    return out


def _stage2(g: LineageGraph, text: str) -> list[Cand]:
    fs = forms(text)
    out: list[Cand] = []
    bodies: dict[str, list[str]] = {}
    for cid in g.columns():
        node = g.nx_graph.nodes[cid]
        uid = node["model"]
        if uid not in bodies:
            bodies[uid] = model_body((g.model_info(uid) or {}).get("name", uid))
        col = split(node["name"])
        best: Cand | None = None
        for f in fs:
            tier, base, rules, cov = _match(f, col, bodies[uid])
            prior, seed = _layer_of(g, cid)
            c = Cand(cid, _col_row(g, cid, tier), tier, base, MODEL_BONUS * cov, prior, seed, rules)
            if best is None or c.raw > best.raw:
                best = c
        assert best is not None
        out.append(best)
    # Amendment D: a text that already is a column's name (no token taken as model context) is not
    # read as "column of model": then no candidate gets the model bonus ("payment method").
    if any(c.tier in ("surface", "rewritten") and c.model_bonus == 0 for c in out):
        for c in out:
            if c.model_bonus:
                c.extra["model_bonus_dropped"] = round(c.model_bonus, 4)
                c.model_bonus = 0.0
    for uid in g.model_ids():
        info = g.model_info(uid) or {}
        if info.get("resource_type") != "model":
            continue
        name = info.get("name", uid)
        mt, q = split(name), [t for t in split(text) if t not in STOPWORDS]
        mtier: Tier
        if q == mt:
            mtier, base = "surface", SURFACE
        elif [rewrite(t) for t in q] == tokens(name):
            mtier, base = "rewritten", REWRITTEN
        else:
            body = model_body(name)
            qb = [rewrite(t) for t in q if t not in LAYER_TOKENS]
            mtier, base = "fuzzy", MODEL_FUZZY * fuzzy(qb, body)
        row = {"id": name, "kind": "model", "match": _MATCH[mtier]}
        out.append(Cand(uid, row, mtier, base))
    return out


def _stage3(g: LineageGraph, text: str, index: SearchIndex) -> list[Cand]:
    out: list[Cand] = []
    bodies: dict[str, list[str]] = {}
    for hit in index.search(text, k=HYBRID_K, kinds=["column"]):
        cid = hit.chunk.column
        if not cid or not g.has_column(cid) or hit.cosine is None or hit.cosine < COS_MIN:
            continue
        uid = g.model_of(cid)
        if uid not in bodies:
            bodies[uid] = model_body((g.model_info(uid) or {}).get("name", uid))
        _, _, _, cov = _match(
            Form(tuple(split(text))), split(g.nx_graph.nodes[cid]["name"]), bodies[uid]
        )
        prior, seed = _layer_of(g, cid)
        rrf_norm = min(hit.score / RRF_MAX, 1.0)
        extra = {"rrf_norm": round(rrf_norm, 4), "bm25_rank": hit.bm25_rank,
                 "dense_rank": hit.dense_rank, "cosine": round(hit.cosine, 4)}  # fmt: skip
        base = HYBRID_BASE + HYBRID_SPAN * rrf_norm
        out.append(Cand(cid, _col_row(g, cid, "hybrid"), "hybrid", base, MODEL_BONUS * cov, prior,
                        seed, extra=extra))  # fmt: skip
    return out


def _rank_key(c: Cand) -> tuple[int, float, int, int, str]:
    return (-int(c.stage == 1), -round(c.raw, 4), int(c.row["kind"] != "column"), c.seed, c.cid)


def link(
    g: LineageGraph, text: str, index: SearchIndex | None = None
) -> tuple[list[Cand], dict[str, Any]]:
    """All candidates >= NO_MATCH, ranked, plus info: ``hybrid`` (unavailable / used / None),
    ``notes``, ``closest`` (below-threshold ids, side record only)."""
    low = text.lower().strip()
    info: dict[str, Any] = {"hybrid": "unavailable" if index is None else None, "notes": []}
    m = _DOTTED.match(text)
    dotted = dotted_column(g, m.group(1), m.group(2)) if m else None
    if dotted is not None:
        if dotted.how == "exact":
            cands = [
                Cand(c, _col_row(g, c, "exact_id"), "exact_id", EXACT_ID) for c in dotted.columns
            ]
        elif dotted.how == "abbreviation":
            cands = [
                Cand(c, _col_row(g, c, "dotted_abbreviation"), "dotted_abbreviation", REWRITTEN,
                     rules=["dotted_abbreviation"])
                for c in dotted.columns
            ]  # fmt: skip
            if len(cands) == 1:
                info["notes"].append(f"interpreted {low} as {g.display_name(cands[0].cid)}")
        else:
            cands = []
            info["closest"] = list(dotted.closest)
        return sorted(cands, key=_rank_key), info

    stage1 = _stage1(g, low)
    stage2 = _stage2(g, text)
    confident = any(c.tier in ("surface", "rewritten") and c.raw >= NO_MATCH for c in stage2)
    stage3: list[Cand] = []
    if index is not None and not stage1 and not confident:
        stage3 = _stage3(g, text, index)
        info["hybrid"] = "used"
    best: dict[str, Cand] = {}
    for c in [*stage1, *stage2, *stage3]:
        old = best.get(c.cid)
        if (
            old is None
            or (c.stage == 1) > (old.stage == 1)
            or ((c.stage == 1) == (old.stage == 1) and c.raw > old.raw)
        ):
            best[c.cid] = c
    ranked = sorted(best.values(), key=_rank_key)
    kept = [c for c in ranked if c.raw >= NO_MATCH]
    if not kept:
        info["closest"] = [c.row["id"] for c in ranked[:CLOSEST] if c.raw > 0]
    return kept, info


def resolve_entity(
    prov: Provenance, args: dict[str, Any], index: SearchIndex | None = None
) -> ToolOutput:
    text = as_str(args, "text")
    assert text is not None
    k = as_int(args, "k", 5, 1, 20)
    ranked, info = link(prov.graph, text, index)
    top = ranked[:k]
    cands = [{**c.row, "score": round(c.score, 3)} for c in top]
    payload: dict[str, Any] = {
        "query": text,
        "candidates": cands,
        "ambiguous": len(top) > 1 and top[0].raw - top[1].raw < AMBIGUOUS_GAP,
    }
    notes = list(info["notes"])
    if not cands:
        notes.append("no candidate matched; try other words or a model name")
    if notes:
        payload["notes"] = notes
    if info["hybrid"]:
        payload["hybrid"] = info["hybrid"]
    side: dict[str, Any] = {
        "scores": {c["id"]: c["score"] for c in cands},
        "parts": {c.row["id"]: c.parts() for c in top},
    }
    if "closest" in info:
        side["closest"] = info["closest"]
    return ToolOutput(payload, side)
