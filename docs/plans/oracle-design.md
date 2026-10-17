# Perturbation oracle: design (S05, v0.3 item A4)

- Status: approved by the owner, 17 Oct 2026 (S05 planner)
- Decision record: ADR 0017. Classification and targets: ADR 0020. Corpus notes: DESIGN_v2 §7.
- Code: `eval/oracle/dlens_oracle/`. Output: `eval/oracle/results/synthetic_shop.json`,
  `corpora/synthetic_shop/ORACLE_REPORT.md`, `corpora/synthetic_shop/oracle_exceptions.yml`.

The oracle is an independent dynamic check of the gold spec. It changes data, re-runs the models'
compiled SQL in DuckDB, records which columns change, and compares the result with
`lineage_spec.yml`.

## 0. Independence

- `dlens_oracle` imports only `dlens.gold_spec` from dlens, plus the stdlib, `yaml` and `duckdb`.
  It never imports `dlens.lineage` (the engine), `dlens.ingest`, `dlens.graph`, or anything that
  reads parser output. A unit test walks the AST of every module in the package and fails on any
  other `dlens` import.
- It has its own `find_dbt`: the executable next to `sys.executable`, else the one on PATH.
- Thresholds (§4) are written by hand from the corpus SQL and DESIGN_v2, read as text.

## 1. Execution

1. Copy `corpora/synthetic_shop` to a temp dir, leaving out `target/`, `*.duckdb` and `logs/`.
   Run `dbt seed`, then `dbt compile --select resource_type:model`. The oracle never runs
   `dbt build` and never runs tests: the data-guarantee tests would fail on perturbed data.
   Everything is offline and local.
2. Read `manifest.json` for each model's `compiled_code` and `depends_on.nodes` (these give the
   topological order and the children map) and for the seed nodes.
3. Open an in-memory DuckDB with `SET threads=1`, which keeps float sums and row order stable.
   Attach it under the catalog name the compiled SQL uses (`synthetic_shop`). Copy the seed tables
   from the dbt-seeded file, so their types are exactly dbt's (decimal money columns). Materialise
   every model as a table in topological order. Staging models are views in dbt, but
   materialisation does not change values. Pristine copies live in schema `base`. Perturbed runs
   work in `main` and are restored from `base` afterwards.
4. Cross-check the manifest's `depends_on` with the spec's `models.<m>.depends_on`. A mismatch is
   reported as SQL drift.

## 2. "Column changed"

**Fingerprint.** For each output column: the table's row count, plus the sorted multiset of the
column's values. Row order is ignored. NULL is its own value. Decimals, dates and strings compare
exactly. Doubles are rounded to 10 significant digits. A column has changed when its fingerprint
differs from base. A row-count change therefore marks every column of that model as changed, and
the record says so (`row_count_changed`).

**Blind spots of this rule, and what covers them.**

| Blind spot | Example | Covered by |
|---|---|---|
| A permutation of values across rows keeps the multiset | `shuffle` of a key that passes through as IDENTITY | `shift` / `relabel` change the values themselves |
| Which row holds which value is not compared | a value moves to another customer | every direct edge also gets a value-changing mode |
| A one-to-one relabel of JOIN / GROUP BY keys is invisible (DESIGN_v2 §7.3) | `raw_web_sessions.id + c` | `break`, `shuffle`, `null_out` |
| An order-preserving shift is invisible to WINDOW / QUALIFY / SORT keys | all `snapshot_date + 37` | `shuffle`, `cross` |
| min / max change only when an extreme row changes | `first_shipped_at` | `scale`, `cross`. Anything left goes on the owner list |
| count / count(DISTINCT) ignore value changes | `order_count` | `null_out`, and `break` for DISTINCT |

**Controls (run once, before any perturbation).**

- (a) Determinism: build base twice and require identical fingerprints. **If this fails, the run
  stops and reports, before any perturbation.**
- (b) Row order: rewrite each parent with its own values in a fixed random row order and re-run
  its children. A child column that changes is *order-sensitive* (a tie in a `row_number` / `lag`
  order key). These columns are reported, and every observation on them carries the flag.
  Category-A cases on order-sensitive columns are never dismissed automatically. They go to the
  owner with the control (b) evidence.

**Errors.** A run that raises (a failed cast, say) is recorded per (column, mode) and never counts
as a change. The report has an errors table. A gold edge whose value-changing modes all errored is
never auto-tagged: it goes on the owner list with the error.

## 3. Perturbation modes

Modes are picked by the column's DuckDB type. Seed `20261017`. "Half" means a row subset drawn by
`random.Random(f"{seed}:{column}:{mode}")`. New values are computed in Python and written back by
`rowid`. A column counts as changed if any mode changes it. Each observation records which modes
changed it and whether the row count changed.

| Type | Modes |
|---|---|
| integer | `relabel` (+1,000,003, one-to-one), `scale` (×3), `cross` (half ×10, the other half → −x), `break` (half → values not present in the column), `shuffle`, `null_out` (half) |
| decimal / double | `shift` (+7.31), `scale` (×1.5), `cross` (half ×10, the other half ×0.1), `shuffle`, `null_out` |
| date / timestamp | `shift` (+37 days, keeps order), `shuffle` (breaks order), `cross` (half +120 d, the other half −120 d), `null_out` |
| varchar | `remap_existing` (most frequent value → second most frequent), `remap_new` (one value → `zz_oracle`, a relabel), `shuffle`, `null_out` |
| boolean | `flip` (all rows), `flip_subset` (half), `null_out` |
| targeted | `nudge:<threshold>`: k = 3 rows (fixed seed) moved to just past the cut-off, in both directions where possible. Added only for a threshold that the modes above cross 0 times |

## 4. Thresholds (`eval/oracle/thresholds.yml`)

Thresholds are written by hand from the SQL, not taken from parser output. Each entry has `id`,
`model`, `line`, `predicate` (verbatim), `cutoffs`, `inputs` (the gold-side parent columns that
the local check perturbs), and a hand-written `probe` SQL over the parent tables. The probe returns
`(key, value, outcome)`. For an (input, mode) pair, the number of crossings is the count of keys
whose `outcome` flips. The nearest base values below and above each numeric or date cut-off are
committed to the results JSON. S02b never committed them.

| Model | Line | Predicate | Cut-off(s) |
|---|---|---|---|
| int_web_sessions_clean | 14–15 | `not is_bot and page_views > 0` | bool, 0 |
| int_shipments_enriched | 10 | `delivery_days > 5` | 5 |
| int_order_items_enriched | 9 | `unit_price < list_price` | column vs column |
| int_orders_enriched | 14–19 | `case status when 'completed' …` | enum map |
| int_order_profit | 22–25 | `… - coalesce(discount_total, 0) > 0` | 0 |
| int_order_attribution | 13 | `session_date <= order_date` (in JOIN ON) | column vs column |
| int_customer_sessions | 4, 9 | `channel <> 'direct'`; `customer_id is not null` | enum, NULL |
| int_order_shipping | 7 | `filter (where is_late_delivery)` | bool |
| int_order_promotions | 10–13 | `promo_channel <> 'internal'` (IN subquery) | enum |
| int_inventory_daily | 18 | `warehouse_code <> 'WH_TEST'` | enum |
| dim_customer_rfm | 22–23 | `recency_days <= 30`, `<= 90` | 30, 90 |
| dim_customer_rfm | 27–28 | `order_count >= 4`, `>= 2` | 4, 2 |
| dim_customer_rfm | 32–33 | `lifetime_value >= 500`, `>= 150` | 500, 150 |
| dim_customer_segments | 6–8 | `rfm_score >= 330`, `rfm_recency_score = 1`, `rfm_score >= 220` | 330, 1, 220 |
| fct_product_performance | 6, 14 | `filter (where is_discounted)`; `order_status_group = 'complete'` | bool, enum |
| fct_shipping_performance | 5, 9 | `case when is_late_delivery`; `shipped_at is not null` | bool, NULL |
| fct_customer_cohorts | 11 | `filter (where previous_order_date is not null)` | NULL |

Rules:
- **No threshold may end with 0 crossings.** If one does, it gets a `nudge` mode and the run is
  repeated.
- **Completeness.** A text scan of each compiled model finds every `WHERE`, `CASE WHEN`,
  `FILTER (WHERE`, `HAVING`, `QUALIFY` and non-equi `JOIN … ON` line. Each hit is either a
  `thresholds.yml` entry or is listed under `not_thresholds:` with a one-line reason (an
  equi-join key, `IS NOT NULL` with no NULLs in base, …). A test asserts full coverage.

## 5. Two checks

**LOCAL (one hop, the main check).** For every seed column and every model column `c` of a parent
`P`: perturb `c` in `P` (all other columns stay as they are), run each direct child's compiled
SELECT, and fingerprint its outputs. The expected set is the gold's one-hop pairs from `c` into
those children: the direct `edges`, plus the `indirect_edges` expanded with
`dlens.gold_spec.expand_indirect` (model columns from the spec inventory, direct pairs from
`edges`). Only `c` changes and only one hop runs, so each edge is tested on its own, and a missing
edge can't hide behind another path. A column with no children is listed as a dead end and nothing
is compared for it.

**END-TO-END.** For every seed column: perturb it (the same modes), re-run every downstream model
in topological order, and fingerprint every model column. The changed set is compared with the
gold's transitive downstream closure, reported twice: direct edges only, and direct + indirect.

## 6. Classification

**A: observed, not in gold.** Local: a changed child column with no one-hop gold pair. E2E: a
changed column outside the direct+indirect closure. This means a spec bug or SQL drift. It must
be zero or decided by the owner. When a case appears, the session stops and shows the owner the
edge, the SQL lines, the modes that changed it, whether the row count changed, and the
order-sensitivity flag. Nobody edits the gold except the owner. Decisions go in
`oracle_exceptions.yml`.

**B: gold pair, not observed (local).** These auto-tags are applied only when their condition
holds exactly:

| Tag | Condition |
|---|---|
| `sort_no_limit` | Gold type SORT on a row-set row (`targets: all`). The child's compiled SQL has no `limit`. The SORT is the outermost ORDER BY: the model has no ordered aggregate (`string_agg` / `array_agg` / `list` … `ORDER BY`) and no window `ORDER BY` on that column (text checks). |
| `row_preserving_join` | All of: (a) gold type JOIN; (b) the target column's direct gold inputs include no column of the perturbed model `P` (the target comes from the other side of the join); (c) the child's row count is unchanged under every mode, `break` and `null_out` included; (d) the target's values are unchanged under every mode. If (a)–(c) hold and (d) fails, the case is not tagged. |
| `constant_target` | The target has at most 1 distinct value in base, and the row count is unchanged under every mode. |
| `filter_not_crossed` | Gold type FILTER or CONDITIONAL, and every threshold of that clause with `c` among its inputs had 0 crossings in every mode. No threshold may end at 0 crossings, so this tag should fire 0 times. |

Everything else goes on the owner list. That includes any edge whose value-changing modes all
errored.

`row_preserving_join` belongs with the expected-invisible cases of DESIGN_v2 §7.3. ADR 0020 gives
the key of a row-set clause an edge to every output column of its SELECT (`targets: all`), because
the key decides which rows exist. But when a LEFT JOIN keeps every row, a column from the other
side keeps its values whatever happens to the key. The edge is real, and value perturbation can't
see it. The report gives the counts per child model, plus 10 tagged cases (fixed seed), each with
its JOIN line and the target's source line, for the owner to spot-check.

**Indirect-only evidence.** Local: child columns that changed although the gold reaches them from
`c` only through indirect pairs. E2E: changed columns in the direct+indirect closure but not in the
direct closure. These counts are the evidence that indirect edges are real.

**E2E B** (in the closure, not observed): reported, split into *explained* (every gold path from
the seed passes through a local category-B edge) and *unexplained* (listed). It is not gated, per
ADR 0017 ("listed, not failed").

**Gated:** local A, E2E A and local B. Every untagged local B case must be in
`oracle_exceptions.yml`, and the committed error list must match.

## 7. Artefacts

- `eval/oracle/dlens_oracle/` (`perturb.py`: build, modes, checks, classification;
  `report.py`: JSON → Markdown). No `eval/__init__.py`. Pytest and mypy reach the package
  through `eval/oracle` on their path.
- `eval/oracle/thresholds.yml`, `eval/oracle/results/synthetic_shop.json`.
- `scripts/run_oracle.py` (a thin CLI) and `make oracle`.
- `corpora/synthetic_shop/ORACLE_REPORT.md`: generated. Its "Owner decisions" section is
  rendered from `oracle_exceptions.yml`.
- `corpora/synthetic_shop/oracle_exceptions.yml`: `category_a` and `category_b`, each entry
  `{from, to, check, type, reason, decision, decided}`. Only the owner supplies `decision`.
- Tests:
  - `tests/unit/oracle/`: the fingerprint, the modes, the tag rules on toy DuckDB models,
    threshold coverage, and independence.
  - `tests/integration/test_oracle.py`: results equal the committed JSON (runtime excepted), no
    undecided A, untagged local B equal to `category_b` (the `engine_gaps.yml` pattern), the
    error list equal to the committed one, and no threshold at 0 crossings.

## 8. Runtime

The run reports its wall time. If the full run takes more than about 2 minutes, it is marked
`slow` and leaves `make test`, which runs a fixed subset instead (seeds `raw_orders`,
`raw_web_sessions`, `raw_shipments`, their local children and their E2E), checked against the
matching slice of the committed JSON. A CI job `oracle` then runs the full oracle and the full
integration test on every push to main.
