.PHONY: test test-fast lint ingest eval-smoke eval-full ui demo-bundle demo-requirements

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

# Public demo (docs/deploy.md): the prebuilt bundle and the light Cloud install (no dbt, no torch).
demo-bundle:
	uv run python scripts/build_demo_bundle.py

demo-requirements:
	{ echo "# Streamlit Community Cloud install for the public demo (Python 3.12)."; \
	  echo "# Generated from uv.lock by 'make demo-requirements'; do not edit by hand."; \
	  echo "# base + agent + ui extras, without dbt (the demo reads a prebuilt graph) and groq."; \
	  uv export --frozen --no-dev --extra agent --extra ui --no-emit-project --no-hashes \
	    --no-header --no-annotate --prune dbt-core --prune dbt-duckdb --prune groq \
	    --format requirements.txt; } > demo/requirements.txt
