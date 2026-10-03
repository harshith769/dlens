"""Live agent smoke on synthetic_shop with local Ollama (skipped in CI).

Asserts the structural expectations in tests/fixtures/agent_smoke.yaml: refused / ambiguity mode,
every cited id in the ledger, every call under the 3,000-token estimate, a run record written.
Answer quality (which gold edge is cited) is printed, not asserted.
"""

import importlib.util
import os
from pathlib import Path

import pytest

from dlens.agent.llm import make_client
from dlens.agent.loop import ask
from dlens.agent.runlog import RunLogger
from dlens.agent.tools import Toolbox
from dlens.graph import LineageGraph

pytestmark = [
    pytest.mark.integration,
    pytest.mark.ollama,
    pytest.mark.skipif(
        os.environ.get("DLENS_RUN_OLLAMA") != "1" or os.environ.get("CI") == "true",
        reason="live Ollama test: set DLENS_RUN_OLLAMA=1 locally",
    ),
]

SCRIPT = Path(__file__).parents[2] / "scripts" / "smoke_agent.py"
_spec = importlib.util.spec_from_file_location("smoke_agent", SCRIPT)
assert _spec and _spec.loader
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

QUESTIONS = smoke.load_questions()["questions"]


@pytest.fixture(scope="module")
def client():
    return make_client("ollama")


@pytest.mark.parametrize("q", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_smoke_question(
    q, client, synthetic_graph: LineageGraph, synthetic_project: Path, tmp_path: Path
):
    toolbox = Toolbox(synthetic_graph, synthetic_project)
    run = ask(q["question"], client, toolbox, RunLogger(tmp_path / "runs"))
    result = smoke.check(q["expect"], run, toolbox)
    print("\n" + smoke.report_row(q["id"], run, result))
    assert result["structural_ok"], result["structural"]
