.PHONY: test lint ingest eval-smoke eval-full

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

ingest:
	@echo "ingest: not implemented yet (CORPUS=$(CORPUS))"

eval-smoke:
	@echo "eval-smoke: not implemented yet"

eval-full:
	@echo "eval-full spends free cloud quota. Check the quota counter first."
	@read -p "Type 'yes' to continue: " ans; [ "$$ans" = "yes" ] || { echo "Aborted."; exit 1; }
	@echo "eval-full: not implemented yet"
