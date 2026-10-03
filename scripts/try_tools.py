"""Run one agent tool on a corpus and pretty-print what the LLM sees and what code keeps.

uv run python scripts/try_tools.py synthetic_shop trace_upstream fct_daily_revenue.revenue_finance
uv run python scripts/try_tools.py synthetic_shop resolve_entity "payment amt" --k 3
uv run python scripts/try_tools.py jaffle_shop get_model_sql orders --around amount
uv run python scripts/try_tools.py synthetic_shop impact_downstream raw_orders.tax_usd --depth 4
"""

import argparse
import json
from pathlib import Path

from dlens.agent.llm.tokens import estimate_tokens
from dlens.agent.llm.types import Message
from dlens.agent.tools import Toolbox
from dlens.graph import load_or_build

CORPORA = Path(__file__).parents[1] / "corpora"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("corpus", help="directory name under corpora/ (or a path)")
    ap.add_argument("tool", choices=[s.name for s in Toolbox.__new__(Toolbox).specs()])
    ap.add_argument("arg", help="column id, model id or search text")
    ap.add_argument("--k", type=int, help="resolve_entity: number of candidates")
    ap.add_argument("--depth", type=int, help="trace/impact: max_depth")
    ap.add_argument("--around", help="get_model_sql: column to centre on")
    ap.add_argument("--indirect", choices=["true", "false"], help="trace/impact: include_indirect")
    ns = ap.parse_args()

    project = Path(ns.corpus) if Path(ns.corpus).is_dir() else CORPORA / ns.corpus
    toolbox = Toolbox(load_or_build(project), project)
    key = {
        "resolve_entity": "text",
        "trace_upstream": "column_id",
        "impact_downstream": "column_id",
        "get_model_sql": "model_id",
    }[ns.tool]
    args: dict[str, object] = {key: ns.arg}
    for name, value in (
        ("k", ns.k),
        ("max_depth", ns.depth),
        ("around_column", ns.around),
        ("include_indirect", ns.indirect),
    ):
        if value is not None:
            args[name] = value
    result = toolbox.call(ns.tool, args)
    tokens = estimate_tokens([Message(role="tool", content=result.content)])
    print(f"== LLM payload ({tokens} est. tokens, cap 1500) ==")
    print(json.dumps(result.llm_payload, indent=2, ensure_ascii=False))
    print("\n== side records (code / validator / UI only) ==")
    print(json.dumps(result.side_records, indent=2, ensure_ascii=False))
    print(f"\nemitted ids: {sorted(toolbox.emitted_ids)}")


if __name__ == "__main__":
    main()
