# Explain: the perturbation oracle (S05, v0.3 A4, ADR 0017)

Files: `eval/oracle/dlens_oracle/build.py` (`compile_corpus`, `Warehouse`, `fingerprint`),
`controls.py` (`determinism`, `row_order`), `modes.py` (`modes_for`, `apply`), `thresholds.py`
(`scan`, `uncovered`, `run_probe`, `crossings`, `nearest`), `gold.py` (`load_gold`, `Gold`),
`perturb.py` (`local_check`, `classify`, `_tag`, `sort_no_limit`), `e2e.py` (`e2e_check`),
`run.py` (`run_oracle`), `report.py` (`render`, `undecided`); `eval/oracle/thresholds.yml`;
`scripts/run_oracle.py` (`make oracle`); outputs `eval/oracle/results/synthetic_shop.json`,
`corpora/synthetic_shop/ORACLE_REPORT.md`; decisions `corpora/synthetic_shop/oracle_exceptions.yml`;
gate `tests/integration/test_oracle.py`. Design: `docs/plans/oracle-design.md`.

## What it does
It checks the gold spec without reading any parser output. It changes data in one column, runs
the models' compiled SQL in DuckDB again, and records which output columns change. Then it
compares that with `lineage_spec.yml`:
- **A**: a column changed that the gold doesn't reach. That is a spec bug or SQL drift, and the
  owner decides it.
- **B**: a gold pair whose target never changed. It is auto-tagged when the reason is certain,
  otherwise the owner decides it.

On synthetic_shop (seed 20261017, about 40 s):
- **0 category-A cases**, one-hop and end-to-end.
- 762 of 907 one-hop gold pairs observed.
- 81 of the 145 unobserved pairs tagged `row_preserving_join`; the other 64 accepted by the owner
  under five reasons.
- 399 one-hop pairs observed through indirect pairs only: the evidence that indirect edges are
  real.

## How it works
1. **Build.** Copy the corpus to a temp dir and run `dbt seed` plus `dbt compile` (never `build`,
   never tests). Read `manifest.json` for the compiled SQL and parents. Load the seeds into an
   in-memory DuckDB (`threads = 1`) under the catalog name the SQL uses, and materialise every
   model as a table in topological order. Pristine copies stay in schema `base`. A run writes
   into `main` and restores from `base` afterwards.
2. **Fingerprint.** For each column: the row count plus a hash of its sorted value multiset (row
   order ignored, doubles rounded to 10 significant digits). A change in row count marks every
   column of the model.
3. **Controls.** (a) Two independent builds must give identical fingerprints, or the run stops
   before perturbing anything. (b) Each parent is rewritten with the same rows in a random order.
   A child column that changes is order-sensitive and gets flagged. synthetic_shop has none.
4. **Modes** (by DuckDB type, fixed seed; "half" is a seeded row subset):
   - integers: relabel (+1,000,003), scale, cross, break, shuffle, null_out
   - decimals: shift, scale, cross, shuffle, null_out
   - dates and timestamps: shift (keeps order), shuffle (breaks order), cross (±120 days),
     null_out
   - strings: remap_existing, remap_new, shuffle, null_out
   - booleans: flip, flip_subset, null_out
   A column counts as changed if any mode changes it.
5. **Thresholds.** `thresholds.yml` lists every cut-off by hand, with a probe query that returns
   `(key, value, outcome)`. A crossing is a key whose outcome flips under a mode. The run records
   crossings per input and mode, and the nearest base values around each cut-off. A text scan of
   the compiled SQL (WHERE, CASE, FILTER, HAVING, QUALIFY, comparisons, JOIN ON) must hit only
   lines that are a threshold or a reasoned `not_thresholds` entry.
6. **One-hop check** (the main check). For every seed and model column `c` of table `P`:
   - Apply each mode to `c`, and run only `P`'s direct children.
   - Compare their changed columns with the gold's one-hop pairs from `c`. Those are the direct
     edges plus the indirect rows expanded by `dlens.gold_spec.expand_indirect` (D7).
   Only `c` changes and only one hop runs, so each edge is tested on its own.
7. **Auto-tags for B** (certain cases only):
   - `sort_no_limit`: no LIMIT, and the column is in no window or ordered-aggregate ORDER BY.
   - `row_preserving_join`: all four hold:
     - the pair is JOIN only;
     - the target's direct inputs contain no column of `P`;
     - the child's row count never changed;
     - the target never changed.
   - `constant_target`: the target column holds at most one distinct value.
   - `filter_not_crossed`: the clause's thresholds had 0 crossings in every mode.
   An edge whose value-changing modes all errored is never tagged.
8. **End-to-end check.**
   - For every seed column, materialise every downstream model under each mode. Compare the
     changed set with the gold closure, direct-only and direct+indirect.
   - Unobserved closure members are *explained* when every gold path crosses a one-hop B pair;
     the rest are listed with a likely reason. These are not gated (ADR 0017).
9. **Gate.** `test_oracle.py` runs everything again and asserts:
   - the results equal the committed JSON (wall time excepted);
   - the error list is unchanged;
   - there is no drift, no uncovered threshold line and no threshold with 0 crossings;
   - every A case has a decision;
   - the untagged B cases **equal** `oracle_exceptions.yml`;
   - the report is up to date.

## Why this design
- **Independence is enforced, not promised.** An AST test fails if `dlens_oracle` imports any
  `dlens` module other than `dlens.gold_spec`. The oracle runs dbt itself and reads only the
  manifest, the seeds and the gold. Neither the spec author nor the engine controls the result.
- **One hop first.** End-to-end alone lets a missing edge hide behind another path: the column
  still changes, via a different route. Perturbing a model column directly in its table isolates
  each edge, even in states that upstream data could never produce. That is the point.
- **Many weak modes beat one strong one.** Every mode has a blind spot: a relabel keeps joins,
  a shuffle keeps multisets, a shift keeps order. Their union covers what each one misses.
  NULL-out is the only mode that moves `count(x)`.
- **Owner-only decisions, equality-tested.** The oracle never edits the gold. A new B case fails
  the test until the owner decides it, and a case that becomes observed fails until its entry is
  removed (the `engine_gaps.yml` pattern).
- **Deterministic.** The seed is fixed, threads = 1, and the base build is checked twice, so the
  committed JSON can be compared exactly.

## Alternatives rejected
- **`dbt build` on perturbed data.** The data-guarantee tests fail on purpose, and the run is
  slower. Running the compiled SQL directly needs no dbt state.
- **Row-level diffs keyed by a primary key.** Many models have no reliable key, and perturbations
  change keys. A multiset per column needs no key. Its blind spots are documented, and the other
  modes cover them.
- **Tagging B cases by heuristic** (any JOIN key, any FILTER). Not certain. Only provable
  conditions are auto-tags; everything else goes to the owner.
- **A second parser as the oracle.** It would share sqlglot's blind spots (ADR 0017). C1 already
  compares with dbt-colibri.
- **Hard-coding the RFM cut-offs from S02b.** Those values were never committed. The thresholds
  file is written from the SQL, and the run commits the nearest values.

## Results
These come from `ORACLE_REPORT.md`, wall time 39 s (dbt 10 s, one-hop 11 s, end-to-end 17 s):
- One-hop pairs by label (confirmed / not observed):

  | Label | Confirmed / not observed |
  |---|---|
  | IDENTITY | 160 / 0 |
  | RENAME | 42 / 0 |
  | TRANSFORMATION | 88 / 0 |
  | AGGREGATION | 73 / 0 |
  | JOIN | 249 / 113 |
  | GROUP_BY | 105 / 12 |
  | FILTER | 87 / 14 |
  | SORT | 20 / 3 |
  | WINDOW | 11 / 3 |
  | CONDITIONAL | 4 / 0 |

- Every direct edge that has a child to observe changes under some mode.
- The owner accepted the 64 untagged B cases in five groups:

  | Reason | Cases |
  |---|---|
  | preserved-side join key | 32 |
  | QUALIFY kept side | 11 |
  | functionally dependent GROUP BY key | 12 |
  | row_number blind spot | 2 |
  | tie-breaker with no ties in base data | 7 |

- End-to-end:
  - 0 category-A cases, and 867 changes reachable only through indirect edges.
  - 902 unobserved columns are explained by a one-hop B pair. 68 are unexplained and listed:
    absorbed by the segment CASE, by LIMIT 10, or by a row-preserving join.
- One structural fact this exposed: `rfm_monetary_score` can never change `customer_segment`.
  It is the units digit of `rfm_score`, and the cut-offs are 330 and 220.

## Explain-back questions
1. Perturbing `stg_refunds.order_id` never changes `int_order_financials.order_date`, yet the gold
   has a JOIN edge between them. Why is the edge right (ADR 0020), and which four conditions let
   the oracle tag it `row_preserving_join`? Why isn't `stg_orders.order_id ->
   int_orders_enriched.order_date` tagged the same way?
2. Suppose the gold forgot the edge `x.k -> m.c`, but `m.c` is still in the end-to-end closure of
   `x.k`'s seed through another path. Why does the end-to-end check report no category A, and how
   does the one-hop check catch the missing edge?
3. `shuffle` keeps each column's value multiset, so it can't change an IDENTITY output. Why is it
   in every mode list anyway? Which mode is the only one that moves `count(session_id)`?
