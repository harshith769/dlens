"""Generate the entity-linker test set (S08, docs/plans/linker-design.md §6).

uv run python scripts/gen_linker_cases.py          # writes eval/linker/{cases,dev_mentions,jira_sample}.jsonl
uv run python scripts/gen_linker_cases.py --check  # exit 1 if the files on disk are stale

Sources: lineage_spec.yml column names (the gold inventory, hand-written from DESIGN_v2) and the
hand-drafted eval/linker/variants.yml. The graph, the parser and dlens's linker are never loaded:
the gold of a case can't come from the system it scores. dbt_jira gold ids are checked against the
project's own model YAML files (models/**/*.yml).

Mechanical variants (exact id, exact bare name, abbreviation, word order, typo, model-qualified)
come from the spec names by fixed rules. A local normaliser (split, plural strip, the design's
abbreviation table) detects collisions: a generated mention that also names another column is
SKIPPED and listed with a reason, never given a guessed gold.

Split (owner, Q4): a stable hash of the case's first gold id (no-match: of the mention) puts about
40% in linker-dev and 60% in linker-test. Gold columns that are dev.jsonl targets always go to
linker-dev.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).parents[1]
SPEC = ROOT / "corpora" / "synthetic_shop" / "lineage_spec.yml"
GAPS = ROOT / "corpora" / "synthetic_shop" / "linker_gaps.yml"
JIRA_MODELS = ROOT / "corpora" / "dbt_jira" / "models"  # gold checked against its YAML files
DEV = ROOT / "eval" / "questions" / "dev.jsonl"
OUT = ROOT / "eval" / "linker"
VARIANTS = OUT / "variants.yml"

DEV_SHARE = 40  # percent of gold columns in linker-dev
PER_LAYER_EXACT = 12
N_BARE_SHARED, N_BARE_UNIQUE = 10, 10
N_WORD_ORDER, N_TYPO, N_QUALIFIED = 20, 10, 8
PER_ABBREVIATION = 2
# Owner, 17 Oct 2026 (case review): drop cases with more than MAX_GOLD gold columns (too weak to
# measure anything) and these mentions. Dropped cases are counted, never backfilled.
MAX_GOLD = 5
DROP_MENTIONS = {"marketing revenue"}  # also reads as attributed_revenue
LAYERS = {"raw": "raw", "stg": "staging", "int": "intermediate", "fct": "marts", "dim": "marts"}

# Design §2.1 (approved): abbreviation -> canonical. Only for collision checks and for making
# abbreviated mentions; the linker has its own copy.
ABBREVIATIONS = {
    "amt": "amount", "qty": "quantity", "cust": "customer", "prod": "product", "num": "number",
    "ts": "timestamp", "dt": "date", "desc": "description", "cat": "category", "addr": "address",
    "pmt": "payment", "txn": "transaction", "avg": "average", "tot": "total", "pct": "percent",
    "percentage": "percent", "promo": "promotion", "rev": "revenue",
}  # fmt: skip
WEAK = {"usd"}
# Design §2.3 stopwords: names containing one make unnatural word-order mentions ("at delivered").
STOPWORDS = set(
    "the a an of per by for on in from at to with each all what which is are does do how where when why column field".split()
)
SHORT = {v: k for k, v in ABBREVIATIONS.items() if k != "percentage"}  # canonical -> abbreviation


def _h(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def _toks(name: str) -> list[str]:
    out = []
    for t in name.lower().replace(".", "_").replace(" ", "_").replace("-", "_").split("_"):
        if not t:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(ABBREVIATIONS.get(t, t))
    return out


def _key(name: str) -> tuple[str, ...]:
    return tuple(_toks(name))


def _weak(name: str) -> tuple[str, ...]:
    """The key without weak tokens (design §2.1: ``usd`` is ignored in the rewritten tier)."""
    kept = tuple(t for t in _toks(name) if t not in WEAK)
    return kept or _key(name)


def _bag(name: str) -> tuple[str, ...]:
    return tuple(sorted(_toks(name)))


def load_spec() -> dict[str, list[str]]:
    spec = yaml.safe_load(SPEC.read_text())
    models: dict[str, list[str]] = dict(spec["seeds"])
    models |= {m: v["columns"] for m, v in spec["models"].items()}
    return models


def layer(model: str) -> str:
    return LAYERS[model.split("_", 1)[0]]


class Builder:
    def __init__(self, models: dict[str, list[str]], dev_targets: set[str]) -> None:
        self.models = models
        self.ids = sorted(f"{m}.{c}" for m, cols in models.items() for c in cols)
        self.by_name: dict[str, list[str]] = defaultdict(list)
        for cid in self.ids:
            self.by_name[cid.split(".")[1]].append(cid)
        self.key_names: dict[tuple[str, ...], set[str]] = defaultdict(set)
        self.bag_names: dict[tuple[str, ...], set[str]] = defaultdict(set)
        self.weak_names: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for name in self.by_name:
            self.key_names[_key(name)].add(name)
            self.bag_names[_bag(name)].add(name)
            self.weak_names[_weak(name)].add(name)
        self.dev_targets = dev_targets
        self.cases: list[dict[str, Any]] = []
        self.skipped: list[str] = []
        self.dropped: Counter[str] = Counter()
        self.unsure: list[dict[str, Any]] = []
        self.used: set[str] = set()

    # -- helpers ---------------------------------------------------------------------------------

    def add(self, variant: str, mention: str, gold: list[str], **kw: Any) -> None:
        low = mention.lower()
        if len(gold) > MAX_GOLD or low in DROP_MENTIONS:
            self.dropped[variant] += 1
            self.skipped.append(f"{variant}: {mention!r} dropped (owner rule: >5 gold or listed)")
            return
        if low in self.used:
            self.skipped.append(f"{variant}: {mention!r} duplicates an earlier mention")
            return
        for g in gold:
            if g not in self.ids:
                raise SystemExit(
                    f"{variant}: gold {g!r} for {mention!r} is not in lineage_spec.yml"
                )
        self.used.add(low)
        amb = kw.pop("ambiguous", None)
        case: dict[str, Any] = {
            "variant": variant,
            "mention": mention,
            "gold": sorted(gold),
            "expect_ambiguous": bool(amb if amb is not None else len(gold) > 1),
            **{k: v for k, v in kw.items() if v is not None},
        }
        self.cases.append(case)
        if "unsure" in case:
            self.unsure.append(case)

    def _pick(self, items: list[str], n: int, salt: str) -> list[str]:
        return sorted(items, key=lambda x: _h(salt + x))[:n]

    def names_are_unique(self, mention: str, name: str, *, bag: bool = False) -> bool:
        """The mention names exactly ``name`` among all spec names: same key, same key without
        weak tokens, and (``bag``) same tokens in any order."""
        return not self.collisions(mention, name, bag=bag)

    def collisions(self, mention: str, name: str, *, bag: bool = False) -> list[str]:
        hits = self.key_names.get(_key(mention), set()) | self.weak_names.get(_weak(mention), set())
        if bag:
            hits |= self.bag_names.get(_bag(mention), set())
        return sorted(hits - {name})

    # -- mechanical variants ---------------------------------------------------------------------

    def exact_ids(self, exclude: set[str]) -> None:
        for lay in ("raw", "staging", "intermediate", "marts"):
            pool = [c for c in self.ids if layer(c.split(".")[0]) == lay and c not in exclude]
            for cid in self._pick(pool, PER_LAYER_EXACT, "exact"):
                self.add("exact_id", cid, [cid], ambiguous=False, source="lineage_spec")

    def bare_names(self, avoid: set[str]) -> None:
        shared = [n for n, ids in self.by_name.items() if len(ids) > 1 and n not in avoid]
        unique = [n for n, ids in self.by_name.items() if len(ids) == 1 and n not in avoid]
        for n in self._pick(shared, N_BARE_SHARED, "bare") + self._pick(
            unique, N_BARE_UNIQUE, "bare"
        ):
            self.add("exact_name", n, self.by_name[n], source="lineage_spec")

    def abbreviations(self) -> None:
        """Both directions: shorten a canonical token (amount -> amt) or expand an abbreviation in
        the name (qty -> quantity). One bare spaced mention and one dotted mention per entry."""
        entries: dict[str, list[tuple[str, str]]] = defaultdict(list)  # entry -> (name, mention)
        for name in sorted(self.by_name):
            parts = name.split("_")
            for i, p in enumerate(parts):
                if p in SHORT:
                    entries[f"{SHORT[p]}->{p}"].append(
                        (name, "_".join(parts[:i] + [SHORT[p]] + parts[i + 1 :]))
                    )
                elif p in ABBREVIATIONS and p != "percentage":
                    entries[f"{p}->{ABBREVIATIONS[p]}"].append(
                        (name, "_".join(parts[:i] + [ABBREVIATIONS[p]] + parts[i + 1 :]))
                    )
        for entry, rows in sorted(entries.items()):
            rows = [(n, m) for n, m in rows if m not in self.by_name]  # never a real name
            ok = [(n, m) for n, m in rows if self.names_are_unique(m, n)]
            for n, m in rows:
                if (n, m) not in ok:
                    self.skipped.append(
                        f"abbreviation {entry}: {m!r} also names {self.collisions(m, n)}"
                    )
            picked = sorted(ok, key=lambda r: _h("abbr" + entry + r[0]))[:PER_ABBREVIATION]
            for j, (n, m) in enumerate(picked):
                if j == 0:
                    self.add(
                        "abbreviation",
                        m.replace("_", " "),
                        self.by_name[n],
                        rule=entry,
                        source="lineage_spec",
                    )
                else:
                    cid = self._pick(self.by_name[n], 1, "abbr-dot")[0]
                    self.add("abbreviation", f"{cid.split('.')[0]}.{m}", [cid], ambiguous=False, rule=entry,
                             source="lineage_spec")  # fmt: skip

    def word_order(self) -> None:
        pool = []
        for name in self.by_name:
            parts = name.split("_")
            if not 2 <= len(parts) <= 3 or len(set(parts)) < len(parts) or STOPWORDS & set(parts):
                continue
            mention = " ".join(reversed(parts))
            if self.names_are_unique(mention, name, bag=True):
                pool.append((name, mention))
            else:
                others = self.collisions(mention, name, bag=True)
                self.skipped.append(f"word_order: {mention!r} also names {others}")
        for name, mention in sorted(pool, key=lambda r: _h("order" + r[0]))[:N_WORD_ORDER]:
            self.add("word_order", mention, self.by_name[name], source="lineage_spec")

    def typos(self) -> None:
        pool = []
        for name, ids in self.by_name.items():
            if len(ids) != 1:
                continue
            parts = name.split("_")
            i = max(range(len(parts)), key=lambda k: (len(parts[k]), -k))
            tok = parts[i]
            if len(tok) < 6:
                continue
            mid = len(tok) // 2
            typo = "_".join(parts[:i] + [tok[:mid] + tok[mid + 1 :]] + parts[i + 1 :])
            if typo in self.by_name or _key(typo) in self.key_names:
                self.skipped.append(f"typo: {typo!r} is another name")
                continue
            pool.append((name, typo))
        for name, typo in sorted(pool, key=lambda r: _h("typo" + r[0]))[:N_TYPO]:
            self.add("typo", typo, self.by_name[name], source="lineage_spec")

    def qualified(self) -> None:
        """'<column words> in <model>' for names carried by >= 2 models: the model decides."""
        pool = [cid for n, ids in self.by_name.items() if len(ids) > 1 for cid in ids]
        for cid in self._pick(pool, N_QUALIFIED, "qual"):
            model, col = cid.split(".")
            self.add("model_qualified", f"{col.replace('_', ' ')} in {model}", [cid], ambiguous=False,
                     source="lineage_spec")  # fmt: skip

    # -- hand-drafted ----------------------------------------------------------------------------

    def hand(self, variants: dict[str, Any], gaps: dict[str, Any]) -> None:
        # the S08 gap items, frozen in resolved_s08 once fixed (still open ones would follow)
        done = gaps.get("resolved_s08", {})
        gaps = {
            "exact_id_top1": [*done.get("exact_id_top1", []), *gaps["exact_id_top1"]],
            "fragile": done.get("fragile", []),
        }
        for g in gaps["exact_id_top1"]:
            self.add("linker_gap", g["id"], [g["id"]], ambiguous=False, source="linker_gaps.yml")
        for f in gaps.get("fragile", []):
            self.add(
                "linker_gap",
                f["query"],
                [f["expected_top1"]],
                ambiguous=False,
                source="linker_gaps.yml",
            )
        for section, variant in (
            ("description", "description"),
            ("phrase", "phrase"),
            ("model_qualified", "model_qualified"),
            ("near_duplicate", "near_duplicate"),
        ):
            for row in variants[section]:
                self.add(variant, row["mention"], row["gold"], ambiguous=row.get("ambiguous"), rule=row.get("rule"),
                         note=row.get("note"), unsure=row.get("unsure"), limitation=row.get("limitation"),
                         source="variants.yml")  # fmt: skip
        for row in variants["no_match"]:
            self.add("no_match", row["mention"], [], note=row.get("note"), unsure=row.get("unsure"),
                     source="variants.yml")  # fmt: skip

    # -- split -----------------------------------------------------------------------------------

    def split(self) -> None:
        for c in self.cases:
            key = c["gold"][0] if c["gold"] else "mention:" + c["mention"].lower()
            dev = (
                any(g in self.dev_targets for g in c["gold"]) or _h("split" + key) % 100 < DEV_SHARE
            )
            c["split"] = "linker-dev" if dev else "linker-test"
        counts = Counter(c["variant"] for c in self.cases)
        seen: Counter[str] = Counter()
        for c in self.cases:
            seen[c["variant"]] += 1
            c["id"] = f"lk-{c['variant']}-{seen[c['variant']]:03d}"
            c["corpus"] = "synthetic_shop"
        assert sum(counts.values()) == len(self.cases)


ORDER = [
    "id",
    "corpus",
    "split",
    "variant",
    "mention",
    "gold",
    "expect_ambiguous",
    "rule",
    "source",
    "note",
    "limitation",
    "unsure",
]


def _row(c: dict[str, Any]) -> str:
    return json.dumps({k: c[k] for k in ORDER if k in c}, ensure_ascii=False)


def dev_mentions(variants: dict[str, Any], models: dict[str, list[str]]) -> list[dict[str, Any]]:
    over = variants.get("dev_mentions", {})
    out = []
    ids = {f"{m}.{c}" for m, cols in models.items() for c in cols}
    for line in DEV.read_text().splitlines():
        q = json.loads(line)
        o = over.get(q["id"], {})
        gold = o.get("gold", [q["target"]])
        assert all(g in ids for g in gold), q["id"]
        out.append({
            "id": q["id"], "corpus": "synthetic_shop", "split": "dev", "mention": o.get("mention", q["target"]),
            "gold": sorted(gold), "expect_ambiguous": len(gold) > 1, "wording": q["wording"],
            **({"note": o["note"]} if "note" in o else {}),
        })  # fmt: skip
    return out


def jira_sample(variants: dict[str, Any]) -> list[dict[str, Any]]:
    ids = set()
    for f in sorted(JIRA_MODELS.rglob("*.yml")):
        doc = yaml.safe_load(f.read_text()) or {}
        ids |= {
            f"{m['name']}.{c['name']}"
            for m in doc.get("models") or []
            for c in m.get("columns") or []
        }
    out = []
    for i, row in enumerate(variants["jira"], 1):
        bad = [g for g in row["gold"] if g not in ids]
        if bad:
            raise SystemExit(f"jira: gold {bad} not in the dbt_jira model YAML")
        out.append({
            "id": f"jira-{i:02d}", "corpus": "dbt_jira", "split": "jira-sample", "variant": row["variant"],
            "mention": row["mention"], "gold": sorted(row["gold"]), "expect_ambiguous": len(row["gold"]) > 1,
            **{k: row[k] for k in ("rule", "note", "unsure") if k in row},
        })  # fmt: skip
    return out


def build() -> tuple[dict[str, str], Builder]:
    models = load_spec()
    variants = yaml.safe_load(VARIANTS.read_text())
    gaps = yaml.safe_load(GAPS.read_text())
    dev_targets = {json.loads(line)["target"] for line in DEV.read_text().splitlines()}
    b = Builder(models, dev_targets)
    b.hand(variants, gaps)  # hand rows first: they own their mentions
    avoid = {m["mention"] for sec in ("near_duplicate",) for m in variants[sec]}
    gap_ids = [*gaps.get("resolved_s08", {}).get("exact_id_top1", []), *gaps["exact_id_top1"]]
    b.exact_ids({g["id"] for g in gap_ids})
    b.bare_names(avoid)
    b.abbreviations()
    b.word_order()
    b.typos()
    b.qualified()
    b.split()
    files = {
        "cases.jsonl": "".join(_row(c) + "\n" for c in b.cases),
        "dev_mentions.jsonl": "".join(json.dumps(r) + "\n" for r in dev_mentions(variants, models)),
        "jira_sample.jsonl": "".join(json.dumps(r) + "\n" for r in jira_sample(variants)),
    }
    return files, b


def summary(b: Builder) -> str:
    by = Counter((c["variant"], c["split"]) for c in b.cases)
    variants = sorted({v for v, _ in by})
    lines = ["| variant | linker-dev | linker-test | total |", "|---|---|---|---|"]
    for v in variants:
        d, t = by[(v, "linker-dev")], by[(v, "linker-test")]
        lines.append(f"| {v} | {d} | {t} | {d + t} |")
    d = sum(n for (_, s), n in by.items() if s == "linker-dev")
    lines.append(f"| **total** | {d} | {len(b.cases) - d} | {len(b.cases)} |")
    rules = Counter((c["rule"], c["split"]) for c in b.cases if c["variant"] == "phrase")
    lines.append("")
    lines.append("phrase rules (dev/test): " + ", ".join(
        f"{r} {rules[(r, 'linker-dev')]}/{rules[(r, 'linker-test')]}" for r in sorted({r for r, _ in rules})))  # fmt: skip
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the files on disk are stale")
    ap.add_argument("--skipped", action="store_true", help="also print skipped mechanical mentions")
    args = ap.parse_args()
    files, b = build()
    if args.check:
        stale = [
            n
            for n, text in files.items()
            if not (OUT / n).exists() or (OUT / n).read_text() != text
        ]
        if stale:
            print(f"stale: {', '.join(stale)} (run scripts/gen_linker_cases.py)")
            return 1
        return 0
    for name, text in files.items():
        (OUT / name).write_text(text)
    print(summary(b))
    print(f"\nskipped mentions: {len(b.skipped)}; unsure cases: {len(b.unsure)}")
    print("dropped by owner rule: " + ", ".join(f"{v} {n}" for v, n in sorted(b.dropped.items())))
    if args.skipped:
        print("\n".join("  " + s for s in b.skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
