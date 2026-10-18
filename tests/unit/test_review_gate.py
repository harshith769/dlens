"""scripts/check_review.py and build_review.py: nothing counts until every decision is set."""

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_review as br  # noqa: E402
import check_review as cr  # noqa: E402

QUESTIONS = br.merged()
MAIN = [q for q in QUESTIONS if not q.get("spare")]
SPARES = [q for q in QUESTIONS if q.get("spare")]


def all_accept() -> dict:
    d = {q["id"]: {"decision": "accept"} for q in MAIN}
    d.update({q["id"]: {"decision": "unused"} for q in SPARES})
    return {"decisions": d}


def test_pending_file_fails_and_all_accept_passes():
    _, problems = cr.final(QUESTIONS, br.decisions(QUESTIONS))
    assert len(problems) == 96 and all("pending" in p for p in problems)
    out, problems = cr.final(QUESTIONS, all_accept())
    assert problems == [] and len(out) == 96


def test_fix_needs_text_and_identifier_fix_keeps_the_target():
    doc = all_accept()
    q = next(q for q in MAIN if q["wording"] == "identifier" and q["type"] == "trace")
    doc["decisions"][q["id"]] = {"decision": "fix"}
    assert any("needs text" in p for p in cr.final(QUESTIONS, doc)[1])
    doc["decisions"][q["id"]] = {"decision": "fix", "text": "Where does it come from?"}
    assert any("must name" in p for p in cr.final(QUESTIONS, doc)[1])
    doc["decisions"][q["id"]] = {"decision": "fix", "text": f"What feeds {q['target']}?"}
    out, problems = cr.final(QUESTIONS, doc)
    assert problems == [] and next(x for x in out if x["id"] == q["id"])["question"].startswith(
        "What"
    )


def test_drop_is_replaced_by_a_same_row_spare_that_takes_the_id():
    spare = SPARES[0]
    victim = next(q for q in MAIN if cr.row(q) == cr.row(spare) and q["wording"] == "identifier")
    other_row = next(q for q in MAIN if cr.row(q) != cr.row(spare))
    doc = all_accept()
    doc["decisions"][victim["id"]] = {"decision": "drop", "replacement": spare["id"]}
    assert any("accept or fix" in p for p in cr.final(QUESTIONS, doc)[1])
    doc["decisions"][spare["id"]] = {"decision": "accept"}
    out, problems = cr.final(QUESTIONS, doc)
    assert problems == []
    new = next(x for x in out if x["id"] == victim["id"])
    assert new["target"] == spare["target"] and new["review"]["replaced_by_spare"] == spare["id"]
    bad = copy.deepcopy(doc)
    bad["decisions"][other_row["id"]] = {"decision": "drop", "replacement": spare["id"]}
    assert any("not" in p or "replaces both" in p for p in cr.final(QUESTIONS, bad)[1])


def test_an_accepted_spare_must_replace_something():
    doc = all_accept()
    doc["decisions"][SPARES[0]["id"]] = {"decision": "accept"}
    assert any("replaces nothing" in p for p in cr.final(QUESTIONS, doc)[1])


def test_wording_shift_needs_a_relabel_or_the_flag():
    doc = all_accept()
    q = next(q for q in MAIN if q["wording"] == "paraphrase")
    doc["decisions"][q["id"]] = {"decision": "accept", "wording": "identifier"}
    assert any("wording mix" in p for p in cr.final(QUESTIONS, doc)[1])
    doc["allow_wording_shift"] = True
    assert cr.final(QUESTIONS, doc)[1] == []


def test_rebuild_keeps_decisions_the_owner_set(tmp_path, monkeypatch):
    f = tmp_path / "dev_decisions.yml"
    monkeypatch.setattr(br, "DECISIONS", f)
    doc = br.decisions(QUESTIONS)
    doc["decisions"]["dev-01"] = {"decision": "accept", "note": "ok"}
    f.write_text(br.render_decisions(doc))
    again = br.decisions(QUESTIONS)
    assert again["decisions"]["dev-01"] == {"decision": "accept", "note": "ok"}
    assert again["decisions"]["dev-02"] == {"decision": "pending"}


def test_review_files_on_disk_are_fresh():
    assert br.OUT_MD.read_text() == br.render(QUESTIONS), "run scripts/build_review.py"
