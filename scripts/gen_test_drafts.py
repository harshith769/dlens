"""Generate the 224 TEST question drafts (S15a, v0.3 D5b; docs/plans/s15a-drafts-design.md).

uv run python scripts/gen_test_drafts.py          # writes eval/questions/drafts/test_draft_v1.jsonl
uv run python scripts/gen_test_drafts.py --check  # exit 1 if the file on disk is stale

Targets come from the TEST pool only (eval/questions/pools.yml). Gold comes only from
lineage_spec.yml through dlens.gold_spec (the D5a Builder in gen_dev_questions.py, split="test"),
plus traps.yml and the hand inputs in eval/questions/drafts/hand/. The graph, the parser and the
linker are never loaded. Paraphrase slots carry the template text and `paraphrase_pending` until
scripts/paraphrase_questions.py has written its picks to eval/questions/drafts/paraphrase_test/;
a rerun then merges them.

Prints counts only, never question text or gold.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gen_dev_questions as g  # noqa: E402


DRAFTS = ROOT / "eval" / "questions" / "drafts"
HAND = DRAFTS / "hand"
ASKS = HAND / "ask_drafts_test.yml"
WORDS = HAND / "unanswerable_words.yml"
PARA = DRAFTS / "paraphrase_test" / "paraphrases.jsonl"
OUT = DRAFTS / "test_draft_v1.jsonl"
SALT = "s15a-test-v1:"
UNITS = ("_usd", "_pct", "_days", "_hours")  # a dotted id omitting one of these is interpreted

# (row, bucket, subtype, wording, n, extra): s15a-drafts-design.md §1. Within each (row, bucket)
# description slots go first (most constrained), as in D5a.
PLAN: list[tuple[str, str | None, str, str, int, dict[str, Any]]] = [
    # Trace 1 (21)
    ("trace", "1", "computed", "identifier", 1, {}),
    ("trace", "1", "computed", "paraphrase", 1, {}),
    ("trace", "1", "multi_part", "identifier", 1, {}),
    ("false_premise", "1", "false_premise", "identifier", 1, {}),
    ("false_premise", "1", "false_premise", "paraphrase", 1, {}),
    ("trace", "1", "upstream", "description", 2, {}),
    ("trace", "1", "upstream", "identifier", 8, {}),
    ("trace", "1", "upstream", "name_words", 3, {}),
    ("trace", "1", "upstream", "paraphrase", 3, {}),
    # Trace 2-3 (28)
    ("trace", "2-3", "computed", "description", 2, {}),
    ("trace", "2-3", "computed", "identifier", 3, {}),
    ("trace", "2-3", "computed", "name_words", 1, {}),
    ("trace", "2-3", "computed", "paraphrase", 1, {}),
    ("trace", "2-3", "ambiguous", "name_words", 2, {}),
    ("trace", "2-3", "multi_part", "identifier", 1, {}),
    ("trace", "2-3", "multi_part", "paraphrase", 1, {}),
    ("false_premise", "2-3", "false_premise", "identifier", 2, {}),
    ("false_premise", "2-3", "false_premise", "paraphrase", 1, {}),
    ("trace", "2-3", "upstream", "description", 2, {}),
    ("trace", "2-3", "upstream", "identifier", 1, {"variant": "unit"}),  # interpreted
    ("trace", "2-3", "upstream", "identifier", 5, {}),
    ("trace", "2-3", "upstream", "name_words", 3, {}),
    ("trace", "2-3", "upstream", "paraphrase", 3, {}),
    # Trace 4-5 (28)
    ("trace", "4-5", "computed", "description", 1, {}),
    ("trace", "4-5", "computed", "identifier", 2, {}),
    ("trace", "4-5", "computed", "name_words", 1, {}),
    ("trace", "4-5", "computed", "paraphrase", 1, {}),
    ("trace", "4-5", "ambiguous", "name_words", 2, {}),
    ("trace", "4-5", "multi_part", "identifier", 2, {}),
    ("false_premise", "4-5", "false_premise", "identifier", 1, {}),
    ("false_premise", "4-5", "false_premise", "paraphrase", 1, {}),
    ("trace", "4-5", "upstream", "description", 2, {}),
    ("trace", "4-5", "upstream", "identifier", 8, {}),
    ("trace", "4-5", "upstream", "name_words", 4, {}),
    ("trace", "4-5", "upstream", "paraphrase", 3, {}),
    # Trace 6+ (28)
    ("trace", "6+", "computed", "identifier", 4, {}),
    ("trace", "6+", "computed", "name_words", 1, {}),
    ("trace", "6+", "computed", "paraphrase", 3, {}),
    ("trace", "6+", "ambiguous", "name_words", 2, {}),
    ("trace", "6+", "multi_part", "identifier", 1, {}),
    ("trace", "6+", "multi_part", "paraphrase", 1, {}),
    ("false_premise", "6+", "false_premise", "identifier", 1, {}),
    ("trace", "6+", "upstream", "description", 1, {}),
    ("trace", "6+", "upstream", "identifier", 8, {}),
    ("trace", "6+", "upstream", "name_words", 3, {}),
    ("trace", "6+", "upstream", "paraphrase", 3, {}),
    # Impact downstream (56)
    ("impact", "1", "downstream", "description", 3, {}),
    ("impact", "1", "downstream", "identifier", 1, {"variant": "unit"}),  # interpreted
    ("impact", "1", "downstream", "identifier", 5, {}),
    ("impact", "1", "downstream", "name_words", 2, {}),
    ("impact", "1", "downstream", "paraphrase", 3, {}),
    ("impact", "2-3", "downstream", "description", 3, {}),
    ("impact", "2-3", "downstream", "identifier", 1, {"variant": "exposures"}),
    ("impact", "2-3", "downstream", "identifier", 1, {"variant": "unit"}),  # interpreted
    ("impact", "2-3", "downstream", "identifier", 4, {}),
    ("impact", "2-3", "downstream", "name_words", 2, {}),
    ("impact", "2-3", "downstream", "paraphrase", 3, {}),
    ("impact", "4-5", "downstream", "description", 2, {}),
    ("impact", "4-5", "downstream", "identifier", 1, {"variant": "exposures_one"}),
    ("impact", "4-5", "downstream", "identifier", 1, {"variant": "exposures"}),
    ("impact", "4-5", "downstream", "identifier", 4, {}),
    ("impact", "4-5", "downstream", "name_words", 2, {}),
    ("impact", "4-5", "downstream", "paraphrase", 2, {}),
    ("impact", "6+", "downstream", "description", 1, {}),
    ("impact", "6+", "downstream", "identifier", 5, {}),
    ("impact", "6+", "downstream", "name_words", 2, {}),
    ("impact", "6+", "downstream", "paraphrase", 3, {}),
    ("impact", "indirect-only", "downstream", "identifier", 3, {}),
    ("impact", "indirect-only", "downstream", "name_words", 1, {}),
    ("impact", "indirect-only", "downstream", "paraphrase", 1, {}),
    # Yes/no (14): 5 yes direct, 3 yes only with indirect edges, 6 no
    ("yesno", None, "yesno", "identifier", 3, {"variant": "yes_direct"}),
    ("yesno", None, "yesno", "paraphrase", 2, {"variant": "yes_direct"}),
    ("yesno", None, "yesno", "identifier", 2, {"variant": "yes_indirect_only"}),
    ("yesno", None, "yesno", "name_words", 1, {"variant": "yes_indirect_only"}),
    ("yesno", None, "yesno", "identifier", 2, {"variant": "no"}),
    ("yesno", None, "yesno", "name_words", 2, {"variant": "no"}),
    ("yesno", None, "yesno", "paraphrase", 2, {"variant": "no"}),
]
# Unanswerable (21): (kind, wording, n)
UNANSWERABLE = [("dotted_near_miss", "identifier", 8), ("dotted_typo", "identifier", 3),
                ("unknown_model", "identifier", 3), ("bare", "name_words", 4),
                ("out_of_domain", "identifier", 1), ("out_of_domain", "paraphrase", 2)]  # fmt: skip
EXPECTED = {"trace": 105, "impact": 70, "ask": 28, "unanswerable": 21}


# ------------------------------------------------------------------------------------ builder
def run_plan(b: g.Builder) -> None:
    for row, bucket, subtype, wording, n, extra in PLAN:
        for _ in range(n):
            slot = g.Slot(row, subtype, wording, bucket, **extra)
            if row == "trace":
                ok = b.fill_trace(slot)
                if not ok and wording == "description":  # no usable description: fall back
                    slot.wording = "name_words"
                    ok = b.fill_trace(slot)
                    if ok:
                        b.questions[-1]["review_flags"].append("wording_fallback: description")
            elif row == "false_premise":
                ok = b.fill_false_premise(slot)
            elif row == "impact":
                ok = b.fill_impact(slot)
                if not ok and wording == "description":
                    slot.wording = "name_words"
                    ok = b.fill_impact(slot)
                    if ok:
                        b.questions[-1]["review_flags"].append("wording_fallback: description")
            else:
                ok = b.fill_yesno(slot)
            if not ok:
                raise SystemExit(f"no test-pool candidate for {row} {bucket} {subtype} {wording}")
            if slot.variant == "unit":
                interpret(b, b.questions[-1])


def unit_short(b: g.Builder, c: str) -> str | None:
    """`c` minus its unit suffix, if that shorter id does not exist (trap-8 interpretation policy)."""
    unit = next((u for u in UNITS if c.endswith(u)), None)
    if unit is None or c[: -len(unit)] in b.ctx.v.model_columns | b.ctx.v.seed_columns:
        return None
    return c[: -len(unit)]


class DraftBuilder(g.Builder):
    """The D5a Builder plus the `unit` slot variant: an interpreted near-miss (M9 v1.2)."""

    def trace_candidates(self, slot: g.Slot) -> list[str]:
        out = super().trace_candidates(slot)
        return [c for c in out if unit_short(self, c)] if slot.variant == "unit" else out

    def impact_candidates(self, slot: g.Slot) -> list[str]:
        out = super().impact_candidates(slot)
        return [c for c in out if unit_short(self, c)] if slot.variant == "unit" else out


def interpret(b: g.Builder, q: dict[str, Any]) -> None:
    """Rewrite a `unit` slot's question to name the unit-omitting near-miss."""
    near = unit_short(b, q["target"])
    assert near is not None
    q["question"] = q["question"].replace(q["target"], near)
    q["mention"] = near
    q["gold"]["interpretation"] = {"text": near, "column": q["target"]}
    q["review_flags"].append("interpretation")


def add_asks(b: g.Builder) -> None:
    ctx = b.ctx
    for a in yaml.safe_load(ASKS.read_text())["asks"]:
        t = a["target"]
        assert t in ctx.test, f"ask {a['key']}: target is not a test-pool column"
        for m in g.DOTTED.findall(a["question"]):
            assert m not in ctx.dev, f"ask {a['key']} names a dev-pool column"
        flags = ["paraphrase_pending"] if a["wording"] == "paraphrase" else []
        q: dict[str, Any] = {
            "corpus": "synthetic_shop", "split": "test", "type": "ask", "subtype": "meaning",
            "question": a["question"], "target": t, "mention": t, "hop_depth": ctx.depth(t),
            "hop_bucket": g.trace_bucket(ctx.depth(t)), "wording": a["wording"], "source": "hand",
            "traps": sorted(a["traps"]), "stratum": "ask|-",
            "gold": {"verdict": "answered", "facts": a["facts"]},
            "expect": {"verdict": "answered", "hand_scored": True},
            "source_lines": [f["source"] for f in a["facts"]], "review_flags": flags,
            "ask_key": a["key"],
        }  # fmt: skip
        if a["wording"] == "paraphrase":
            q["template_question"] = a["question"]
        b.add(q)


def unanswerable_mentions(b: g.Builder) -> list[tuple[str, str, str]]:
    """(kind, wording, mention) for the 21 unanswerable drafts, derived deterministically."""
    ctx = b.ctx
    words = yaml.safe_load(WORDS.read_text())
    ids = ctx.v.model_columns | ctx.v.seed_columns
    bare_names = {c.split(".")[1] for c in ids}
    used_models: set[str] = set()
    out: list[tuple[str, str, str]] = []
    cols = sorted((c for c in ctx.test & ctx.v.model_columns if "_id" not in c), key=b.h)

    def absent(mention: str) -> bool:
        model, col = mention.split(".")
        if mention in ids or any(
            mention == c[: -len(u)] for c in ids for u in UNITS if c.endswith(u)
        ):
            return False
        return col not in set(ctx.v.models.get(model, []))

    for kind, wording, n in UNANSWERABLE:
        got = 0
        if kind == "dotted_near_miss":
            for i, c in enumerate(cols):
                if got == n:
                    break
                model, col = c.split(".")
                if model in used_models:
                    continue
                if got % 2 == 0:  # drop the last name part (never a unit: those are interpreted)
                    parts = col.split("_")
                    if len(parts) < 2 or f"_{parts[-1]}" in UNITS:
                        continue
                    near = "_".join(parts[:-1])
                else:  # append a suffix from the word list
                    sfx = words["near_miss_suffixes"][i % len(words["near_miss_suffixes"])]
                    if col.endswith(sfx):
                        continue
                    near = col + sfx
                m = f"{model}.{near}"
                if absent(m) and near not in bare_names:
                    out.append((kind, wording, m))
                    used_models.add(model)
                    got += 1
        elif kind == "dotted_typo":
            for c in cols:
                if got == n:
                    break
                model, col = c.split(".")
                if model in used_models or len(col) < 6:
                    continue
                i = 2 + int(b.h("typo:" + c), 16) % (len(col) - 3)
                if col[i] == col[i + 1] or "_" in col[i : i + 2]:
                    continue
                typo = col[:i] + col[i + 1] + col[i] + col[i + 2 :]
                m = f"{model}.{typo}"
                if absent(m) and typo not in bare_names:
                    out.append((kind, wording, m))
                    used_models.add(model)
                    got += 1
        elif kind == "unknown_model":
            for model, c in zip(words["unknown_models"], cols[::-1], strict=False):
                assert model not in ctx.v.models and model not in ctx.v.seeds
                out.append((kind, wording, f"{model}.{c.split('.')[1]}"))
                got += 1
        elif kind == "bare":
            for phrase in words["bare"][:n]:
                assert phrase.replace(" ", "_") not in bare_names
                out.append((kind, wording, phrase))
                got += 1
        else:
            done = sum(1 for k, _, _ in out if k == "out_of_domain")
            for m in words["out_of_domain"][done : done + n]:
                assert m.split(".")[0] not in ctx.v.models
                out.append((kind, wording, m))
                got += 1
        if got != n:
            raise SystemExit(f"unanswerable {kind}: {got} of {n}")
    return out


def add_unanswerable(b: g.Builder) -> None:
    ctx = b.ctx
    ids = sorted(ctx.v.model_columns | ctx.v.seed_columns)
    for kind, wording, mention in unanswerable_mentions(b):
        bare = mention.split(".")[-1].replace(" ", "_")
        model = mention.split(".")[0] if "." in mention else None
        pool = [f"{model}.{c}" for c in ctx.v.models[model]] if model in ctx.v.models else ids
        closest = difflib.get_close_matches(bare, [c.split(".")[1] for c in pool], n=3, cutoff=0.5)
        tmpl = "impact" if int(b.h("tmpl:" + mention), 16) % 2 else "upstream"
        text = g.TEMPLATES[tmpl].format(t=mention)
        flags = ["paraphrase_pending"] if wording == "paraphrase" else []
        q: dict[str, Any] = {
            "corpus": "synthetic_shop", "split": "test", "type": "unanswerable", "subtype": kind,
            "question": text, "target": mention, "mention": mention, "hop_depth": None,
            "hop_bucket": None, "wording": wording, "source": "template",
            "traps": ["near_duplicate_names"] if kind == "dotted_near_miss" and any(
                mention.split(".")[1] in c or c.split(".")[1] in mention
                for c in ctx.trap_cols.get("near_duplicate_names", set())) else [],
            "stratum": "unanswerable|-",
            "gold": {"verdict": "refused", "edges": [], "closest": closest},
            "expect": {"verdict": "refused"}, "source_lines": [], "review_flags": flags,
        }  # fmt: skip
        if wording == "paraphrase":
            q["template_question"] = text
        b.add(q)


# ---------------------------------------------------------------------------------- finalise
def merge_paraphrases(questions: list[dict[str, Any]]) -> None:
    if not PARA.is_file():
        return
    rows = {r["id"]: r for r in map(json.loads, PARA.read_text().splitlines())}
    for q in questions:
        r = rows.get(q["draft_id"])
        if "paraphrase_pending" not in q["review_flags"] or not r:
            continue
        if r["template"] != q["template_question"]:
            continue  # stale row: the template changed
        q["review_flags"].remove("paraphrase_pending")
        if r["pick"]:
            q["question"] = r["pick"]
            q["review_flags"].append(f"paraphrase_pick: {r['pick_style']}")
        else:
            q["review_flags"].append("no_clean_paraphrase")


def finalise(b: g.Builder) -> list[dict[str, Any]]:
    out = []
    for i, q in enumerate(b.questions, 1):
        q["id"] = f"test-{i:03d}"
        q["draft_id"] = f"t1-{i:03d}"
        q["gold_source"] = "spec"
        q["review"] = {"decision": "pending", "fixed_text": None, "note": None}
        out.append(q)
    merge_paraphrases(out)
    return out


def build() -> list[dict[str, Any]]:
    b = DraftBuilder(g.load_ctx(), split="test", salt=SALT, trap_min=4, next_id=1)
    run_plan(b)
    add_asks(b)
    add_unanswerable(b)
    questions = finalise(b)
    n = Counter(q["type"] for q in questions)
    assert dict(n) == EXPECTED, dict(n)
    return questions


ORDER = ["id", "draft_id", "corpus", "split", "type", "subtype", "question", "template_question",
         "target", "mention", "hop_depth", "hop_bucket", "wording", "source", "traps", "stratum",
         "ask_key", "gold_source", "gold_meta", "gold", "expect", "source_lines", "review_flags",
         "review"]  # fmt: skip


def render(questions: list[dict[str, Any]]) -> str:
    rows = []
    for q in questions:
        assert set(q) <= set(ORDER), set(q) - set(ORDER)
        rows.append(json.dumps({k: q[k] for k in ORDER if k in q}, ensure_ascii=False))
    return "\n".join(rows) + "\n"


def summary(questions: list[dict[str, Any]]) -> str:
    c = Counter(q["type"] for q in questions)
    w = Counter(q["wording"] for q in questions)
    flags = Counter(re.sub(r":.*", "", f) for q in questions for f in q["review_flags"])
    return f"types {dict(sorted(c.items()))}; wording {dict(sorted(w.items()))}; flags {dict(sorted(flags.items()))}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the drafts file is stale")
    args = ap.parse_args()
    questions = build()
    text = render(questions)
    if args.check:
        stale = not OUT.is_file() or OUT.read_text() != text
        print("test_draft_v1.jsonl is stale" if stale else "test_draft_v1.jsonl is fresh")
        return int(stale)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {len(questions)} drafts to {OUT.relative_to(ROOT)}; {summary(questions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
