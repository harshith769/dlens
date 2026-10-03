.PHONY: test test-fast lint ingest eval-smoke eval-full

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

eval-smoke:
	@echo "eval-smoke: not implemented yet"

eval-full:
	@echo "eval-full spends free cloud quota. Check the quota counter first."
	@read -p "Type 'yes' to continue: " ans; [ "$$ans" = "yes" ] || { echo "Aborted."; exit 1; }
	@echo "eval-full: not implemented yet"
