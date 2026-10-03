# Contributing to DLens

Thanks for helping. DLens is pre-1.0, so small, focused changes are easiest to review.

## Setup

```bash
git clone https://github.com/harshith769/dlens.git && cd dlens
uv sync --extra agent
make test    # unit + golden + property + integration (runs dbt on the vendored corpora)
make lint    # ruff check, ruff format --check, mypy
```

Python 3.12 or 3.13. Always use `uv run ...`, not a bare `pip`. Install the hooks with
`uv run pre-commit install` (ruff and gitleaks).

## Reporting bugs

Open an issue with the bug template. The most useful report is a *minimal* SQL model (and the
schema of its inputs) with the edge you expected and the edge DLens produced.

## Adding or changing SQL construct support

1. Add `tests/golden/fixtures/<name>.sql` and `<name>.expected.json`. Write the expected edges by
   reasoning from the SQL, **before** running the engine; never paste engine output as the answer.
2. If DLens cannot handle it yet, mark the fixture with a top-level `"xfail": "<reason>"` (strict).
3. Regenerate the support matrix: `uv run python scripts/gen_support_matrix.py`.
4. Changes in `src/dlens/lineage/` also update `docs/explain/lineage.md` (what, how, why,
   alternatives rejected).

## Ground rules

- One change per pull request, with a test. `make test` and `make lint` must pass.
- Conventional commits (`feat(lineage): ...`, `fix(graph): ...`, `docs: ...`).
- Parse only compiled SQL from `target/compiled`, always with a catalog schema.
- The frozen benchmark question files under `eval/questions/` and their `.sha256` files must not
  be edited.
- The public interfaces in `docs/DLENS_SPEC.md` section 7 are stable. To change one, open an ADR
  in `docs/adr/` first.
- Keep to the scope in spec section 5. Diff (comparing the lineage of two columns) is
  planned for v1.x; comparing two versions of a project is out of scope.
- Never commit keys or `.env`.

## Releases

Maintainers bump `version` in `pyproject.toml` (the only place), update `CHANGELOG.md`, and push a
`v*` tag. The release workflow builds, publishes to TestPyPI, smoke-tests the install, then
publishes to PyPI through Trusted Publishing (the `pypi` environment waits for a reviewer).

By contributing you agree that your work is licensed under Apache-2.0.
