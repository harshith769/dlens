# sqlglot: `lineage()` node `downstream` order depends on `PYTHONHASHSEED`

Status: **draft for the owner to file** (not filed, not posted anywhere).
Found in S15a/S15e on dbt_jira. DLens works around it (ADR 0030).

- sqlglot 30.21.0 (the version DLens pins); default dialect
- Python 3.12

## Minimal reproduction

```python
# repro.py
from sqlglot.lineage import lineage

sql = """
with lhs as (select amt * 2 as amt_x from t),
     rhs as (select amt - 1 as amt_y from t)
select lhs.amt_x + rhs.amt_y as amt_mix from lhs cross join rhs
"""
node = lineage("amt_mix", sql, schema={"t": {"amt": "int"}})
print([d.name for d in node.downstream])
```

```
$ for s in 0 1 2 3 4 5; do PYTHONHASHSEED=$s python repro.py; done
['lhs.amt_x', 'rhs.amt_y']
['lhs.amt_x', 'rhs.amt_y']
['rhs.amt_y', 'lhs.amt_x']
['rhs.amt_y', 'lhs.amt_x']
['lhs.amt_x', 'rhs.amt_y']
['rhs.amt_y', 'lhs.amt_x']
```

## Expected
The same order on every run. Source order (`lhs.amt_x`, then `rhs.amt_y`) would be the natural
choice.

## Cause
`sqlglot/lineage.py` (30.21.0, line 364):

```python
source_columns = set(find_all_in_scope(select, exp.Column))
```

Iterating a set of expressions follows their hashes, and those hash strings, so the order
changes with `PYTHONHASHSEED`. Deduplicating in first-seen order (for example
`list(dict.fromkeys(find_all_in_scope(select, exp.Column)))`) would keep the dedup and make the
order stable.
