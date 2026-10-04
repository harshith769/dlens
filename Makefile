.PHONY: test test-fast lint ingest eval-smoke eval-full ui

test:
	uv run pytest

test-fast:
	uv run pytest -m "not integration"

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

ingest:
	@test -n "$(CORPUS)" || { echo "usage: make ingest CORPUS=jaffle_shop"; exit 1; }
	uv run dlens ingest corpora/$(CORPUS)

# Dev-set report on local Ollama; the LLM cache in eval/cache makes re-runs free (no quota).
eval-smoke:
	DLENS_PROVIDER=ollama DLENS_CACHE_DIR=eval/cache uv run python scripts/dev_report.py

eval-full:
	@echo "eval-full spends free cloud quota. Check the quota counter first."
	@read -p "Type 'yes' to continue: " ans; [ "$$ans" = "yes" ] || { echo "Aborted."; exit 1; }
	@echo "eval-full: not implemented yet"

# Local UI on Ollama: Ask | Explore lineage | How it works (needs: uv sync --extra agent --extra ui).
ui:
	uv run --extra agent --extra ui streamlit run src/dlens/ui/app.py
