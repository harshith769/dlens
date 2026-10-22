# S0-gold (pilot dev)

metrics-design 1.2 · metrics.py 1.3.0 · dev.jsonl sha256 c265015ae72d · bootstrap 1000×, seed 20261019, CI only for n ≥ 10

Manifest: `{"git_commit": "4a5296d9eb86c5ee91744d89f54d89653889ae29", "hybrid": false, "linker": null, "max_depth": 50, "model": "dlens-graph", "note": "S0-gold (no linker)", "provider": "s0-gold", "questions_file": "eval/questions/dev.jsonl", "questions_sha256": "c265015ae72d62d4e2865493a50fba408e3e7c3ff4afafd2a5f992e425c5fe11", "record_count": 84, "records_file": "s0-gold-dev.jsonl", "required": ["dev-01", "dev-02", "dev-03", "dev-04", "dev-05", "dev-06", "dev-07", "dev-08", "dev-09", "dev-10", "dev-11", "dev-12", "dev-13", "dev-14", "dev-15", "dev-16", "dev-17", "dev-18", "dev-19", "dev-20", "dev-21", "dev-22", "dev-23", "dev-24", "dev-25", "dev-26", "dev-27", "dev-28", "dev-29", "dev-30", "dev-31", "dev-32", "dev-33", "dev-34", "dev-35", "dev-36", "dev-37", "dev-38", "dev-39", "dev-40", "dev-41", "dev-42", "dev-43", "dev-44", "dev-45", "dev-46", "dev-47", "dev-48", "dev-49", "dev-50", "dev-51", "dev-52", "dev-53", "dev-54", "dev-55", "dev-56", "dev-57", "dev-58", "dev-59", "dev-60", "dev-61", "dev-62", "dev-63", "dev-64", "dev-65", "dev-66", "dev-67", "dev-68", "dev-69", "dev-70", "dev-71", "dev-72", "dev-73", "dev-74", "dev-75", "dev-76", "dev-89", "dev-90", "dev-91", "dev-92", "dev-93", "dev-94", "dev-95", "dev-96"], "system": "s0-gold", "view": "validated"}`

Complete: True

| metric | mean [95% CI] (n) |
|---|---|
| node_f1 | 1.000 [1.00, 1.00] (n=68) |
| trace_f1 | 1.000 [1.00, 1.00] (n=44) |
| impact_f1 | 1.000 [1.00, 1.00] (n=24) |
| upstream_f1 | 1.000 [1.00, 1.00] (n=29) |
| inputs_f1 | 1.000 [1.00, 1.00] (n=15) |
| inputs_f1_tolerant | 1.000 [1.00, 1.00] (n=15) |
| columns_f1 | 1.000 [1.00, 1.00] (n=24) |
| models_f1 | 1.000 [1.00, 1.00] (n=24) |
| exposures_f1 | 1.000 [1.00, 1.00] (n=24) |
| yesno_correct | 1.000 (n=6) |
| refusal_correct | 1.000 (n=9) |
| false_refusal | 0.000 [0.00, 0.00] (n=75) |
| chain_correct | 1.000 (n=2) |
| clarify_correct | 1.000 (n=1) |
| interpretation_correct | – |
| premise_rejected | 1.000 (n=4) |
| uncovered_part_correct | 0.000 (n=3) |
| path_node_coverage | 1.000 [1.00, 1.00] (n=29) |
| fully_correct | 1.000 [1.00, 1.00] (n=84) |
| hallucination_rate | 0.000 [0.00, 0.00] (n=80) |
| has_hallucination | 0.000 [0.00, 0.00] (n=74) |
| citation_valid_answer | 1.000 [1.00, 1.00] (n=71) |
| citation_coverage | 1.000 [1.00, 1.00] (n=71) |

Citations checked 982, valid 982, r_ facts 0, model-level macro bucket 0, disagreements with R3 0.
Mentions removed by the negation rule: 10. CTE references: 0. Truncated payloads: none.
Latency p50 0.1 ms, p95 9.8 ms over 84 uncached runs (0 cached, excluded). Tokens/question mean 0.0, LLM calls/question mean 0.0.

## Pass routes (metrics-design v1.2: field / prose / both / neither)

| rule | field | prose | both | neither | n |
|---|---|---|---|---|---|
| interpretation | 0 | 0 | 0 | 0 | 0 |
| uncovered | 0 | 0 | 0 | 3 | 3 |
| premise | 0 | 4 | 0 | 0 | 4 |

Spurious-field diagnostics (not scored; answered predictions): non-empty `uncovered_parts` on non-multi-part questions 0 / 71; `premise_corrected = true` on non-false-premise questions 0 / 70.

## node-set F1 by breakdown

**hop_bucket**: 1 1.000 [1.00, 1.00] (n=14); 2-3 1.000 [1.00, 1.00] (n=19); 4-5 1.000 [1.00, 1.00] (n=16); 6+ 1.000 [1.00, 1.00] (n=17); indirect-only 1.000 (n=2)

**wording**: description 1.000 (n=8); identifier 1.000 [1.00, 1.00] (n=35); name_words 1.000 [1.00, 1.00] (n=10); paraphrase 1.000 [1.00, 1.00] (n=15)

**type**: impact 1.000 [1.00, 1.00] (n=24); trace 1.000 [1.00, 1.00] (n=44)

**subtype**: ambiguous 1.000 (n=2); computed 1.000 [1.00, 1.00] (n=11); downstream 1.000 [1.00, 1.00] (n=24); false_premise 1.000 (n=4); multi_part 1.000 (n=3); upstream 1.000 [1.00, 1.00] (n=24)

**source**: hand 1.000 [1.00, 1.00] (n=14); template 1.000 [1.00, 1.00] (n=36); v0.2 1.000 [1.00, 1.00] (n=18)

**trap**: case_transformation 1.000 (n=6); deep_chain 1.000 [1.00, 1.00] (n=17); doc_injection 1.000 (n=2); exposures 1.000 [1.00, 1.00] (n=15); fan_in_aggregate 1.000 (n=5); join_key_only 1.000 (n=2); near_duplicate_names 1.000 (n=6); none 1.000 [1.00, 1.00] (n=23); rename_chain 1.000 (n=3); select_star 1.000 [1.00, 1.00] (n=22); stale_doc 1.000 (n=3); two_revenue_definitions 1.000 [1.00, 1.00] (n=10); union_all 1.000 (n=5); window_function 1.000 (n=2)

**linker_test_seen**: False 1.000 [1.00, 1.00] (n=54); True 1.000 [1.00, 1.00] (n=14)

## Per question (values below 1.0, and every miss)

| id | subtype | mode | kind | metric | value |
|---|---|---|---|---|---|
| dev-23 | multi_part | direct | answered | uncovered_part_correct | 0.000 |
| dev-32 | multi_part | direct | answered | uncovered_part_correct | 0.000 |
| dev-34 | multi_part | direct | answered | uncovered_part_correct | 0.000 |
