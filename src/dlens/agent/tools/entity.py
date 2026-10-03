"""resolve_entity (fuzzy v1): free text -> ranked candidate columns and models.

Pure stdlib. Order of evidence, strongest first (scores are comparable across tiers):
  1.00  the text is a full id, a ``model.column`` id or a model name, exactly (case-insensitive)
  0.97  the text equals a column name literally (``refund_amt`` -> every column called that)
  0.93  the text equals a column name after normalisation (``refund amount``, ``RefundAmt``)
  <0.90 fuzzy: token overlap + difflib ratio over model and column tokens
Normalisation lower-cases, splits on ``_ . space`` and camelCase, strips a plural ``s`` and maps
abbreviations to one canonical token. Literal and normalised matches are kept in separate tiers on
purpose: ``refund_amt``, ``refund_amount`` and ``refunded_amount`` are different columns
(synthetic_shop trap ``near_duplicate_names``) and must not collapse into one.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from dlens.agent.tools.common import ToolOutput, as_int, as_str
from dlens.agent.tools.provenance import Provenance

# Abbreviation -> canonical token. Entries come from the vocabulary of the corpora we benchmark on
# (raw_payments.amt, qty-style names in dbt projects); extend with a test when a corpus needs it.
ABBREVIATIONS = {
    "amt": "amount",
    "qty": "quantity",
    "cust": "customer",
    "custs": "customer",
    "prod": "product",
    "num": "number",
    "no": "number",
    "ts": "timestamp",
    "dt": "date",
    "desc": "description",
    "cat": "category",
    "addr": "address",
    "pmt": "payment",
    "txn": "transaction",
    "tx": "transaction",
    "ref": "refund",
    "avg": "average",
    "tot": "total",
}
WEAK_TOKENS = {"usd"}  # kept in names, ignored when comparing ("payment amount" ~ amount_usd)
LAYER_TOKENS = {"raw", "stg", "int", "fct", "dim"}  # model-name prefixes: noise when matching
TOP_FUZZY = 0.89
MIN_SCORE = 0.30
AMBIGUOUS_GAP = 0.05


def tokens(text: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    out = []
    for t in re.split(r"[^A-Za-z0-9]+", spaced):
        t = t.lower()
        if not t:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(ABBREVIATIONS.get(t, t))
    return out


def core(toks: list[str]) -> list[str]:
    kept = [t for t in toks if t not in WEAK_TOKENS]
    return kept or toks


def _soft_dice(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    total = 0.0
    for t in a:
        best = max(difflib.SequenceMatcher(None, t, u).ratio() for u in b)
        total += best if best >= 0.8 else 0.0
    return 2 * total / (len(a) + len(b))


def _ratio(a: list[str], b: list[str]) -> float:
    return difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()


def _fuzzy(q: list[str], model_toks: list[str], col_toks: list[str]) -> float:
    both = col_toks + [t for t in model_toks if t not in col_toks]
    overlap = max(_soft_dice(q, col_toks), 0.9 * _soft_dice(q, both))
    seq = max(_ratio(q, col_toks), 0.9 * _ratio(q, both))
    return TOP_FUZZY * (0.7 * overlap + 0.3 * seq)


def resolve_entity(prov: Provenance, args: dict[str, Any]) -> ToolOutput:
    text = as_str(args, "text")
    assert text is not None
    k = as_int(args, "k", 5, 1, 20)
    g = prov.graph
    low = text.lower().strip()
    q = core(tokens(text))
    q_nolayer = [t for t in q if t not in LAYER_TOKENS] or q
    scored: list[tuple[float, int, str, dict[str, str]]] = []  # (score, is_seed, id, row)

    for cid in g.columns():
        node = g.nx_graph.nodes[cid]
        name, model_uid = node["name"], node["model"]
        info = g.model_info(model_uid) or {}
        mname = info.get("name", model_uid)
        short = f"{mname}.{name}".lower()
        col_core = core(tokens(name))
        if low in (cid, short):
            score, match = 1.0, "exact"
        elif low == name.lower():
            score, match = 0.97, "exact"
        elif (
            "." in low
            and tokens(low.rsplit(".", 1)[0]) == tokens(mname)
            and core(tokens(low.rsplit(".", 1)[1])) == col_core
        ):
            score, match = 0.93, "normalised"
        elif q == col_core and "." not in low:
            score, match = 0.93, "normalised"
        else:
            model_toks = [t for t in tokens(mname) if t not in LAYER_TOKENS]
            score, match = _fuzzy(q_nolayer, model_toks, col_core), "fuzzy"
        if score >= MIN_SCORE:
            seed = int(info.get("resource_type") == "seed")
            row = {"id": g.display_name(cid), "kind": "column", "match": match}
            scored.append((score, seed, cid, row))

    for uid in g.model_ids():
        info = g.model_info(uid) or {}
        if info.get("resource_type") != "model":
            continue
        mname = info.get("name", uid)
        mtoks = tokens(mname)
        if low in (uid, mname.lower()):
            score, match = 1.0, "exact"
        elif q == core(mtoks):
            score, match = 0.93, "normalised"
        else:
            body = [t for t in mtoks if t not in LAYER_TOKENS]
            score, match = TOP_FUZZY * 0.9 * _soft_dice(q_nolayer, body), "fuzzy"
        if score >= MIN_SCORE:
            scored.append((score, 0, uid, {"id": mname, "kind": "model", "match": match}))

    scored.sort(key=lambda t: (-round(t[0], 4), t[1], t[2]))
    top = scored[:k]
    cands = [{**row, "score": round(s, 3)} for s, _, _, row in top]
    payload: dict[str, Any] = {
        "query": text,
        "candidates": cands,
        "ambiguous": len(top) > 1 and top[0][0] - top[1][0] < AMBIGUOUS_GAP,
    }
    if not cands:
        payload["notes"] = ["no candidate matched; try other words or a model name"]
    return ToolOutput(payload, {"scores": {c["id"]: c["score"] for c in cands}})
