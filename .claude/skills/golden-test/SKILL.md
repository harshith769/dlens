---
name: golden-test
description: Add a golden test for a SQL construct to the lineage engine (a .sql fixture plus an expected-edges JSON), reasoning-first, and run only that test. Use when adding or changing support for a SQL construct, or when the engine disagrees with an expected file.
---

# Golden test: one fixture per SQL construct (spec §13, §18)

Files live in `tests/golden/fixtures/`; the runner is `tests/golden/test_constructs.py`, the harness
(inline schema, no dbt) is `tests/golden/_harness.py`. Model is always `m`; ids are short
`table.column` (`orders.id`, `m.total`).

## Add a construct
1. Write `fixtures/<name>.sql` using tables from `SCHEMA` in `_harness.py` (`db.main.orders`,
   `customers`, `order_items`, `products`, `employees`, `refunds`, `payments`). Need another
   table? Add it to `_TABLES`.
2. **Reasoning first.** Write `fixtures/<name>.expected.json` BEFORE running the engine, from the
   SQL and the strongest-kind rule (DESIGN.md): AGGREGATION > TRANSFORMATION > RENAME > IDENTITY;
   a pure pass-through is IDENTITY if the leaf name equals the output name, else RENAME; a cast or
   CASE is TRANSFORMATION; join/group/filter/window keys are not edges.
   ```json
   {"edges": [{"from": "orders.id", "to": "m.id", "kind": "IDENTITY"}],
    "quality": "FULL", "constants": [], "deferred": [], "notes": "why, in one line"}
   ```
   Optional keys: `constants` (outputs reading no column), `deferred` (`[from, to]` window keys),
   `partial` (what is not captured; makes the support matrix say `partial`), `xfail`, `justification`.
3. Run only that test: `uv run pytest tests/golden/test_constructs.py -k <name>`.
4. Regenerate the support table: `uv run python scripts/gen_support_matrix.py`
   (a test fails if `docs/explain/lineage.md` is stale).

## If the engine disagrees
Decide which is wrong and say why: re-derive your expectation from the rule first.
- Engine bug: fix `src/dlens/lineage/` (core module: update `docs/explain/lineage.md`), keep the fixture.
- Genuinely unsupported: add `"xfail": "<reason>"` (strict xfail; it fails loudly once fixed).
- **Never edit an expected file just to match output.** A deliberate change to an expected file needs
  a one-line `"justification"` in that file.
- Never generate expected files from engine output, and never use `lineage_spec.yml` this way.
