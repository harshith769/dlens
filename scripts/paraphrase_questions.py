"""Local paraphrases for the dev question candidates (S09, questions-design.md §6).

uv run --extra agent python scripts/paraphrase_questions.py     # Ollama only; cache in eval/cache

For every candidate flagged `paraphrase_pending`, qwen3:4b (through LLMClient, provider ollama;
no other provider is accepted) rewrites the TEMPLATE TEXT ONLY. It never sees gold, the target,
the type or the corpus. Three fixed styles give 3 candidates; automatic checks flag drift; the
first unflagged candidate is picked. Output:
- eval/questions/review/paraphrases.jsonl: one row per question {id, template, candidates, pick}
- eval/questions/review/paraphrases.md: every candidate with its flags, flagged questions first.
The review builder (scripts/build_review.py) merges the picks into the review files. A row whose
template no longer matches the candidate's template is stale and ignored there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
REVIEW = ROOT / "eval" / "questions" / "review"
CANDIDATES = REVIEW / "dev_candidates.jsonl"
OUT_JSONL = REVIEW / "paraphrases.jsonl"
OUT_MD = REVIEW / "paraphrases.md"

SYSTEM = (
    "Rewrite this question in different words. Keep every identifier written like name.name "
    "exactly as written. Do not add or remove information. Do not repeat the original sentence: "
    "change its wording or structure. Reply with the question only."
)
STYLES = [
    ("plain", "neutral, plain wording"),
    ("short", "as few words as possible"),
    ("conversational", "the way a colleague would ask in a chat message"),
]
DOTTED = re.compile(r"\b[a-z_0-9]+\.[a-z_0-9]+\b")
SNAKE = re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b")
INTENTS = [  # first match wins
    ("computed", re.compile(r"\b(computed|calculated|calculation|formula|worked out)\b", re.I)),
    ("trace", re.compile(r"\b(come[s]? from|source[sd]?|origin\w*|derived|fed|feeds?)\b", re.I)),
    ("impact", re.compile(r"\b(affect\w*|impact\w*|break\w*|downstream|depend\w*)\b", re.I)),
]
YESNO = re.compile(r"^\s*(if\b.*,\s*)?(does|do|is|are|would|will|can|could|should)\b", re.I)
VALUE_WORDS = re.compile(r"\b(affect\w*|impact\w*|break\w*|chang\w*)\b", re.I)
PART_WORDS = {"who owns it": ["own"], "how often is it refreshed": ["refresh"],
              "how much does it cost to compute": ["cost"]}  # fmt: skip
FILLER = re.compile(r"^(hey|hi|so|ok|okay|quick question|just quick|just|um)\b\s*")
STOP = {"the", "a", "an", "of", "for", "in", "on", "to", "and", "or", "is", "it", "does", "do"}


def intent(text: str) -> str | None:
    return next((name for name, rx in INTENTS if rx.search(text)), None)


def norm_tokens(text: str) -> set[str]:
    out = set()
    for w in re.split(r"[^a-z0-9]+", text.lower()):
        if w and w not in STOP:
            out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


def check(template: str, cand: str, mention: str | None = None) -> list[str]:
    """Automatic flags for one candidate (questions-design.md §6). Empty = clean."""
    flags = []
    t_norm, c_norm = (re.sub(r"\W+", " ", x.lower()).strip() for x in (template, cand))
    if t_norm == c_norm:
        flags.append("unchanged")
    elif FILLER.sub("", c_norm).strip() == t_norm:
        flags.append("near_unchanged")  # only a filler word in front ("Hey, ...")
    t_ids, c_ids = set(DOTTED.findall(template)), set(DOTTED.findall(cand))
    if t_ids - c_ids:
        flags.append("id_dropped")
    if (c_ids - t_ids) or (set(SNAKE.findall(cand)) - set(SNAKE.findall(template)) - c_ids
                           - {p for i in t_ids for p in i.split(".")}):  # fmt: skip
        flags.append("id_added")
    if mention and not DOTTED.fullmatch(mention) and not norm_tokens(mention) <= norm_tokens(cand):
        flags.append("entity_changed")
    if intent(template) != intent(cand) and intent(template) is not None:
        flags.append("intent_changed")
    if bool(YESNO.search(template)) != bool(YESNO.search(cand)):
        flags.append("intent_changed")
    if "lineage" in template and not re.search(r"\b(lineage|downstream)\b", cand, re.I):
        flags.append("lineage_dropped")
    if "lineage" in template and VALUE_WORDS.search(cand):
        flags.append("value_wording")
    for part, keys in PART_WORDS.items():
        if part in template and not any(k in cand.lower() for k in keys):
            flags.append("part_dropped")
    ratio = len(cand) / max(len(template), 1)
    if not 0.6 <= ratio <= 2.0:
        flags.append("length")
    if "\n" in cand.strip() or cand.count("?") > max(template.count("?"), 1) or not cand.strip():
        flags.append("format")
    if re.match(r"^\s*(sure|here|rewritten|paraphrase)\b", cand, re.I):
        flags.append("format")
    return sorted(set(flags))


def clean(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


Chat = Callable[[str, str], str]  # (style hint, template) -> text


def ollama_chat(cache_dir: Path | None = None) -> Chat:
    from dlens.agent.llm import base
    from dlens.agent.llm.types import Message

    env = {**os.environ, "DLENS_PROVIDER": "ollama"}
    if cache_dir is not None:  # D5b drafts: keep test text out of the shared eval/cache
        env["DLENS_CACHE_DIR"] = str(cache_dir)
    env.setdefault("DLENS_CACHE_DIR", str(ROOT / "eval" / "cache"))
    client = base.make_client("ollama", env)
    assert client.provider.name == "ollama", "paraphrases are local only"

    def chat(hint: str, template: str) -> str:
        msgs = [Message(role="system", content=SYSTEM),
                Message(role="user", content=f"Style: {hint}.\n\n{template}")]  # fmt: skip
        return client.chat(msgs).text

    return chat


def seeded_pick(cands: list[dict[str, Any]], key: str, salt: str) -> dict[str, Any] | None:
    """D5b: among the unflagged candidates, index sha256(salt + key) mod n_clean."""
    clean = [c for c in cands if not c["flags"]]
    if not clean:
        return None
    return clean[int(hashlib.sha256((salt + key).encode()).hexdigest(), 16) % len(clean)]


def paraphrase(
    questions: Iterable[dict[str, Any]],
    chat: Chat,
    id_field: str = "id",
    pick_salt: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for q in questions:
        if "paraphrase_pending" not in q.get("review_flags", []):
            continue
        template = q["template_question"]  # the paraphraser sees this text and nothing else
        cands = []
        for style, hint in STYLES:
            text = clean(chat(hint, template))
            mention = q.get("mention") if isinstance(q.get("mention"), str) else None
            cands.append({"style": style, "text": text, "flags": check(template, text, mention)})
        if pick_salt is None:
            pick = next((c for c in cands if not c["flags"]), None)
        else:
            pick = seeded_pick(cands, q[id_field], pick_salt)
        rows.append({
            "id": q[id_field], "template": template, "candidates": cands,
            "pick": pick["text"] if pick else None, "pick_style": pick["style"] if pick else None,
        })  # fmt: skip
    return rows


def render_md(rows: list[dict[str, Any]]) -> str:
    def flagged(r: dict[str, Any]) -> bool:
        return r["pick"] is None or any(c["flags"] for c in r["candidates"])

    lines = [
        "# Paraphrase candidates (S09, local qwen3:4b)",
        "",
        "GENERATED by scripts/paraphrase_questions.py. Questions with any flagged candidate come "
        "first; a question with no clean candidate keeps its template text (`no_clean_paraphrase`).",
        "",
        "| id | style | candidate | flags | picked |",
        "|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (not flagged(r), r["id"])):
        lines.append(f"| {r['id']} | template | {r['template']} | | |")
        for c in r["candidates"]:
            mark = "yes" if r["pick_style"] == c["style"] else ""
            text = c["text"].replace("|", "\\|").replace("\n", " ")
            lines.append(f"| | {c['style']} | {text} | {', '.join(c['flags'])} | {mark} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inp", type=Path, default=CANDIDATES, help="candidates JSONL")
    ap.add_argument("--out-dir", type=Path, default=None, help="default: eval/questions/review")
    ap.add_argument("--cache-dir", type=Path, default=None, help="default: eval/cache")
    ap.add_argument("--id-field", default="id", help="row key (D5b drafts: draft_id)")
    ap.add_argument("--pick-salt", default=None, help="seeded pick among clean candidates (D5b)")
    args = ap.parse_args()
    if (os.environ.get("DLENS_PROVIDER") or "ollama").lower() != "ollama":
        print("refusing: paraphrases are generated with local Ollama only (DLENS_PROVIDER=ollama)")
        return 2
    questions = [json.loads(x) for x in args.inp.read_text().splitlines()]
    rows = paraphrase(questions, ollama_chat(args.cache_dir), args.id_field, args.pick_salt)
    out_jsonl, out_md = OUT_JSONL, OUT_MD
    if args.out_dir is not None:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        out_jsonl, out_md = args.out_dir / "paraphrases.jsonl", args.out_dir / "paraphrases.md"
        from dlens.agent.llm import ollama

        manifest = {"model": ollama.DEFAULT_MODEL, "provider": "ollama", "temperature": 0,
                    "num_ctx": ollama.NUM_CTX, "seed": ollama.SEED, "styles": [s for s, _ in STYLES],
                    "system_prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
                    "pick": "first clean" if args.pick_salt is None else
                    f"sha256({args.pick_salt!r} + {args.id_field}) mod n_clean"}  # fmt: skip
        (args.out_dir / "paraphrase_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
    out_jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    out_md.write_text(render_md(rows))
    picked = sum(1 for r in rows if r["pick"])
    print(f"{len(rows)} questions, {picked} with a clean paraphrase; see {out_md.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
