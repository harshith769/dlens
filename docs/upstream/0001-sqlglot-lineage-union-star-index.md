# sqlglot: `lineage()` raises for the 2nd+ column of a UNION whose branch is `SELECT *` over an unknown table

Status: **draft for the owner to file** (not filed, not posted anywhere).
Found in S14 E4b on nba-monte-carlo (`initialize_seeding`), see `docs/real-world-coverage.md`.

- sqlglot 30.21.0 (the version DLens pins); default dialect (same on `duckdb`)
- Python 3.12

## Minimal reproduction

```python
from sqlglot.lineage import lineage

sql = "SELECT a, b FROM x UNION ALL SELECT * FROM y"
schema = {"x": {"a": "int", "b": "int"}}  # y is not in the schema

lineage("a", sql, schema=schema)  # works
lineage("b", sql, schema=schema)  # raises
```

## Expected
Both columns behave the same way. Column `a` returns a lineage tree whose second branch ends in
a `Star` node on `y` (the star cannot be expanded without a schema):

```
a -> [('UNION', 'Alias'), ('0', 'Alias'), ('x.a', 'Table'), ('0', 'Star'), ('*', 'Table')]
```

The expectation for `b` is the same shape: `('1', 'Alias') -> x.b`, and `y`'s branch ending in
the unexpanded `*`.

## Actual

```
SqlglotError: Cannot find column's source with index 1 in query: SELECT * FROM y AS y
```

The UNION branch is matched to the outer column by position. The unexpanded `SELECT *` has a
single projection (`*`), so index 0 resolves (to the star) but any index ≥ 1 is out of range and
raises.

## Notes
- With `y` in the schema (`{"y": {"a": "int", "b": "int"}}`) both columns resolve correctly
  (`y.a`, `y.b`), so the issue is only the unknown-schema path.
- Real-world shape: `with t as (select a, b from x union all select * from y) select t.* from t`
  in a dbt model whose upstream relation wasn't built, so it isn't in the catalog.
- Workaround in a caller: catch the error and report the column as an unexpanded `*` gap, as is
  already done for index 0.
