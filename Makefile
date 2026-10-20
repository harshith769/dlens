.PHONY: test test-fast lint ingest eval-smoke eval-s0 eval-s1 eval-full oracle ui demo-bundle demo-requirements check-review

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

# S0 graph oracle (S10): no LLM. Writes eval/runs/s0/ (S0-gold, S0-linked hybrid off) and scores
# both with eval/metrics.py into eval/reports/s0_*_dev.{json,md}.
eval-s0:
	uv run python eval/systems/s0.py
	uv run python eval/metrics.py --records eval/runs/s0/s0-gold-dev.jsonl --system s0-gold \
	  --out eval/reports/s0_gold_dev --title "S0-gold on the 96 dev questions"
	uv run python eval/metrics.py --records eval/runs/s0/s0-linked-dev.jsonl --system s0-linked \
	  --out eval/reports/s0_linked_dev --title "S0-linked (hybrid off) on the 96 dev questions"

# S1 vector-RAG baseline (S11): provider from DLENS_PROVIDER (default ollama, local and free); a
# cloud provider is refused unless s1.py gets --allow-cloud. Cached in eval/cache (re-runs free).
# Writes eval/runs/s1/ and scores it into eval/reports/s1_smoke_dev.{json,md}.
S1_RECORDS ?= eval/runs/s1/s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl
eval-s1:
	DLENS_CACHE_DIR=eval/cache uv run --extra agent --extra retrieval python eval/systems/s1.py
	uv run python eval/metrics.py --records $(S1_RECORDS) --system s1-qwen3-4b \
	  --out eval/reports/s1_smoke_dev \
	  --title "S1 (vector RAG, local qwen3:4b) on the 96 dev questions"

# Dev question review gate (S09): every owner decision set, counts match the table.
check-review:
	uv run python scripts/check_review.py

# Perturbation oracle (S05): offline, free; writes eval/oracle/results/ and ORACLE_REPORT.md.
oracle:
	uv run python scripts/run_oracle.py

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
