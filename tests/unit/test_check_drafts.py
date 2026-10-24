"""scripts/check_drafts.py: the draft checks on small synthetic fixtures (no real draft is read)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_drafts as cd  # noqa: E402
import gen_dev_questions as g  # noqa: E402

CTX = g.load_ctx()


def q(**kw):
    base = {
        "id": "test-001", "draft_id": "t1-001", "corpus": "synthetic_shop", "split": "test",
        "type": "trace", "subtype": "upstream", "question": "Where does a.b come from?",
        "target": "a.b", "mention": "a.b", "hop_depth": 1, "hop_bucket": "1",
        "wording": "identifier", "source": "template", "traps": [], "gold": {"verdict": "answered"},
        "gold_source": "spec", "expect": {}, "source_lines": [], "review_flags": [],
        "review": {"decision": "pending", "fixed_text": None, "note": None},
    }  # fmt: skip
    base.update(kw)
    return base


def test_near_duplicates_equal_text_and_jaccard():
    rows = [
        q(draft_id="t1-001", question="Where does x.y come from?"),
        q(draft_id="t1-002", question="where does X.Y come from"),  # equal after normalising
        q(draft_id="t1-003", question="Where does x.z come from?"),  # one token differs: 5/7
    ]
    assert cd.near_duplicates(rows) == ["t1-001~t1-002"]
    assert cd.near_duplicates(rows[2:], [{"id": "dev-01", "question": "Where does x.z come from?"}])


def test_row_key_and_counts_allow_short():
    yes = q(type="impact", subtype="yesno", gold={"reach": {"direct": "no", "all": "yes"}})
    assert cd.row_key(yes) == ("yesno", "yes_indirect_only")
    assert cd.row_key(q()) == ("trace", "1", "upstream")
    rep = cd.Report()
    cd.check_counts([q()], {("trace", "1", "upstream"): 2}, rep, "c", allow_short=False)
    assert rep.failures["c"]
    rep = cd.Report()
    cd.check_counts([q()], {("trace", "1", "upstream"): 2}, rep, "c", allow_short=True)
    assert not rep.failures["c"] and rep.short == {"trace/1/upstream": 1}
    rep = cd.Report()
    cd.check_counts([q(), q()], {("trace", "1", "upstream"): 1}, rep, "c", allow_short=True)
    assert rep.failures["c"], "too many is never allowed"


def test_schema_flags_missing_keys_pending_paraphrase_and_duplicates():
    bad = q(
        draft_id="t1-002", id="test-002", wording="paraphrase", review_flags=["paraphrase_pending"]
    )
    probs = cd.check_schema(
        [q(), q(), bad, {"draft_id": "t1-009"}], "test", "synthetic_shop", "spec"
    )
    text = " ".join(probs)
    assert "duplicate t1-001" in text and "t1-009 missing" in text
    assert (
        "t1-002 paraphrase without template_question" in text
        and "t1-002 paraphrase_pending" in text
    )


def test_gold_columns_skip_facts_and_closest():
    gold = {
        "upstream": {"all": ["m.c", "m.d"]},
        "facts": [{"fact": "x.y", "source": "p:1"}],
        "closest": ["n.e"],
        "models": {"all": ["m"]},
        "reach": {"from": "m.c", "to": "k.l"},
    }
    assert cd.gold_columns(gold) == {"m.c", "m.d", "k.l"}


def test_d5_one_trace_and_one_impact_per_column():
    rows = [q(), q(draft_id="t1-002"), q(type="impact", subtype="downstream")]
    assert cd.check_d5(rows) == ["trace x2 a.b"]


def test_absent_detects_existing_columns_and_models():
    real = sorted(CTX.v.model_columns)[0]
    model = real.split(".")[0]
    assert cd.absent_problems(q(type="unanswerable", target=real), CTX, cd.SS_DIR)
    assert not cd.absent_problems(q(type="unanswerable", target=f"{model}.zz_nope"), CTX, cd.SS_DIR)
    assert not cd.absent_problems(
        q(type="unanswerable", target="fct_nope.order_id"), CTX, cd.SS_DIR
    )
    assert not cd.absent_problems(q(type="unanswerable", target="moon phase"), CTX, cd.SS_DIR)
    bare = real.split(".")[1].replace("_", " ")
    assert cd.absent_problems(q(type="unanswerable", target=bare), CTX, cd.SS_DIR)


def test_fact_sources_must_exist_and_stale_doc_needs_sql(tmp_path):
    (tmp_path / "corpora").mkdir()
    (tmp_path / "corpora" / "m.sql").write_text("select 1\n\nfrom t\n")
    (tmp_path / "corpora" / "s.yml").write_text("doc: x\n")
    ok = q(type="ask", gold={"facts": [{"fact": "f", "source": "corpora/m.sql:1"}]},
           traps=["stale_doc"])  # fmt: skip
    assert cd.fact_problems(ok, tmp_path) == []
    blank = q(type="ask", gold={"facts": [{"fact": "f", "source": "corpora/m.sql:2"}]})
    assert cd.fact_problems(blank, tmp_path)
    missing = q(type="ask", gold={"facts": [{"fact": "f", "source": "corpora/none.sql:1"}]})
    assert cd.fact_problems(missing, tmp_path)
    yml_only = q(type="ask", traps=["stale_doc"],
                 gold={"facts": [{"fact": "f", "source": "corpora/s.yml:1"}]})  # fmt: skip
    assert cd.fact_problems(yml_only, tmp_path) == ["t1-001 stale-doc facts cite no SQL"]


def test_recompute_catches_an_edited_gold_set():
    t = next(c for c in sorted(CTX.test & CTX.v.model_columns) if CTX.depth(c))
    gold = g.gold_trace(CTX, t)
    row = q(target=t, gold=gold)
    assert cd.recompute_problems(row, CTX) == []
    row["gold"] = {**gold, "upstream": {"direct": [], "all": []}}
    assert cd.recompute_problems(row, CTX) == ["t1-001 gold.upstream"]


def test_external_hash_and_nodes():
    export = {"meta": {"graph_sha256": "abc", "dlens_version": "9.9"}, "nodes": ["m.c", "m.d"]}
    text = json.dumps(export)
    sha = cd.export_sha(text)
    meta = {"graph_sha256": "abc", "export_sha256": sha, "dlens_version": "9.9"}
    good = q(split="external", corpus="dbt_jira", gold_source="parser", gold_meta=meta,
             gold={"upstream": {"all": ["m.c"]}})  # fmt: skip
    bad = q(draft_id="t1-002", id="test-002", split="external", corpus="dbt_jira",
            gold_source="parser", gold_meta={**meta, "graph_sha256": "old"},
            gold={"upstream": {"all": ["m.x"]}})  # fmt: skip
    rep = cd.Report()
    cd.check_external(
        [good, bad], text, rep, allow_short=True, ext_rows={("trace", "1", "upstream"): 2}
    )
    assert rep.failures["set E: graph_sha256 / export hash / engine version recorded"] == [
        "t1-002 gold_meta hash"
    ]
    assert rep.failures["set E: every gold node exists in the graph"] == ["t1-002 1 unknown nodes"]
