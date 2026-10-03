import json
from pathlib import Path

from dlens.agent.runlog import RunLogger, RunRecord, Step, runs_dir


def test_runs_dir_resolution(tmp_path: Path):
    assert runs_dir({"DLENS_RUN_DIR": str(tmp_path)}) == tmp_path
    assert runs_dir({"XDG_STATE_HOME": "/x"}) == Path("/x/dlens/runs")
    assert runs_dir({}) == Path.home() / ".local/state/dlens/runs"


def test_write_appends_one_line_per_run(tmp_path: Path):
    log = RunLogger(tmp_path)
    rec = RunRecord(run_id="r1", started_at="2026-10-05T10:00:00+00:00", question="q")
    rec.steps.append(Step(index=0, phase="code"))
    p1 = log.write(rec)
    p2 = log.write(rec.model_copy(update={"run_id": "r2"}))
    assert p1 == p2 == tmp_path / "2026-10-05.jsonl"
    lines = p1.read_text().splitlines()
    assert [json.loads(x)["run_id"] for x in lines] == ["r1", "r2"]
    assert rec.llm_calls == 0
