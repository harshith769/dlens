# S0-linked (hybrid off) on the 96 dev questions

metrics-design 1.1 · metrics.py 1.1.0 · dev.jsonl sha256 c265015ae72d · bootstrap 1000×, seed 20261019, CI only for n ≥ 10

Manifest: `{"git_commit": "4a5296d9eb86c5ee91744d89f54d89653889ae29", "hybrid": false, "linker": "link() without the hybrid stage", "max_depth": 50, "model": "dlens-graph", "note": "S0-linked (hybrid off)", "provider": "s0-linked", "questions_file": "eval/questions/dev.jsonl", "questions_sha256": "c265015ae72d62d4e2865493a50fba408e3e7c3ff4afafd2a5f992e425c5fe11", "record_count": 84, "records_file": "s0-linked-dev.jsonl", "required": ["dev-01", "dev-02", "dev-03", "dev-04", "dev-05", "dev-06", "dev-07", "dev-08", "dev-09", "dev-10", "dev-11", "dev-12", "dev-13", "dev-14", "dev-15", "dev-16", "dev-17", "dev-18", "dev-19", "dev-20", "dev-21", "dev-22", "dev-23", "dev-24", "dev-25", "dev-26", "dev-27", "dev-28", "dev-29", "dev-30", "dev-31", "dev-32", "dev-33", "dev-34", "dev-35", "dev-36", "dev-37", "dev-38", "dev-39", "dev-40", "dev-41", "dev-42", "dev-43", "dev-44", "dev-45", "dev-46", "dev-47", "dev-48", "dev-49", "dev-50", "dev-51", "dev-52", "dev-53", "dev-54", "dev-55", "dev-56", "dev-57", "dev-58", "dev-59", "dev-60", "dev-61", "dev-62", "dev-63", "dev-64", "dev-65", "dev-66", "dev-67", "dev-68", "dev-69", "dev-70", "dev-71", "dev-72", "dev-73", "dev-74", "dev-75", "dev-76", "dev-89", "dev-90", "dev-91", "dev-92", "dev-93", "dev-94", "dev-95", "dev-96"], "system": "s0-linked", "view": "validated"}`

Complete: True

| metric | mean [95% CI] (n) |
|---|---|
| node_f1 | 0.868 [0.78, 0.94] (n=68) |
| trace_f1 | 0.909 [0.82, 0.98] (n=44) |
| impact_f1 | 0.792 [0.62, 0.92] (n=24) |
| upstream_f1 | 0.897 [0.76, 1.00] (n=29) |
| inputs_f1 | 0.933 [0.80, 1.00] (n=15) |
| inputs_f1_tolerant | 0.933 [0.80, 1.00] (n=15) |
| columns_f1 | 0.792 [0.62, 0.92] (n=24) |
| models_f1 | 0.792 [0.62, 0.92] (n=24) |
| exposures_f1 | 0.792 [0.62, 0.92] (n=24) |
| yesno_correct | 1.000 (n=6) |
| refusal_correct | 1.000 (n=9) |
| false_refusal | 0.107 [0.04, 0.17] (n=75) |
| chain_correct | 1.000 (n=2) |
| clarify_correct | 1.000 (n=1) |
| premise_rejected | 1.000 (n=4) |
| path_node_coverage | 0.897 [0.76, 1.00] (n=29) |
| fully_correct | 0.893 [0.82, 0.95] (n=84) |
| hallucination_rate | 0.000 [0.00, 0.00] (n=72) |
| has_hallucination | 0.000 [0.00, 0.00] (n=66) |
| citation_valid_answer | 1.000 [1.00, 1.00] (n=63) |
| citation_coverage | 1.000 [1.00, 1.00] (n=63) |

Citations checked 882, valid 882, r_ facts 0, model-level macro bucket 0, disagreements with R3 0.
Mentions removed by the negation rule: 10. CTE references: 0. Truncated payloads: none.
Latency p50 0.2 ms, p95 61.2 ms over 84 uncached runs (0 cached, excluded). Tokens/question mean 0.0, LLM calls/question mean 0.0.

## node-set F1 by breakdown

**hop_bucket**: 1 0.786 [0.57, 1.00] (n=14); 2-3 0.842 [0.68, 1.00] (n=19); 4-5 0.875 [0.69, 1.00] (n=16); 6+ 0.941 [0.82, 1.00] (n=17); indirect-only 1.000 (n=2)

**wording**: description 0.000 (n=8); identifier 1.000 [1.00, 1.00] (n=35); name_words 0.900 [0.70, 1.00] (n=10); paraphrase 1.000 [1.00, 1.00] (n=15)

**type**: impact 0.792 [0.62, 0.92] (n=24); trace 0.909 [0.82, 0.98] (n=44)

**subtype**: ambiguous 1.000 (n=2); computed 0.909 [0.73, 1.00] (n=11); downstream 0.792 [0.62, 0.92] (n=24); false_premise 1.000 (n=4); multi_part 1.000 (n=3); upstream 0.875 [0.71, 1.00] (n=24)

**source**: hand 1.000 [1.00, 1.00] (n=14); template 0.750 [0.61, 0.89] (n=36); v0.2 1.000 [1.00, 1.00] (n=18)

**trap**: case_transformation 0.500 (n=6); deep_chain 0.941 [0.82, 1.00] (n=17); doc_injection 1.000 (n=2); exposures 0.867 [0.67, 1.00] (n=15); fan_in_aggregate 0.800 (n=5); join_key_only 1.000 (n=2); near_duplicate_names 1.000 (n=6); none 0.870 [0.70, 1.00] (n=23); rename_chain 1.000 (n=3); select_star 0.955 [0.86, 1.00] (n=22); stale_doc 1.000 (n=3); two_revenue_definitions 0.900 [0.70, 1.00] (n=10); union_all 0.600 (n=5); window_function 1.000 (n=2)

**linker_test_seen**: False 0.889 [0.80, 0.96] (n=54); True 0.786 [0.57, 1.00] (n=14)

## Per question (values below 1.0, and every miss)

| id | subtype | mode | kind | metric | value |
|---|---|---|---|---|---|
| dev-21 | upstream | direct | refused | false_refusal | 1.000 |
| dev-21 | upstream | direct | refused | upstream_f1 | 0.000 |
| dev-21 | upstream | direct | refused | headline_f1 | 0.000 |
| dev-21 | upstream | direct | refused | path_node_coverage | 0.000 |
| dev-21 | upstream | direct | refused | fully_correct | 0.000 |
| dev-27 | computed | direct | refused | false_refusal | 1.000 |
| dev-27 | computed | direct | refused | inputs_f1 | 0.000 |
| dev-27 | computed | direct | refused | inputs_f1_tolerant | 0.000 |
| dev-27 | computed | direct | refused | headline_f1 | 0.000 |
| dev-27 | computed | direct | refused | fully_correct | 0.000 |
| dev-28 | upstream | direct | refused | false_refusal | 1.000 |
| dev-28 | upstream | direct | refused | upstream_f1 | 0.000 |
| dev-28 | upstream | direct | refused | headline_f1 | 0.000 |
| dev-28 | upstream | direct | refused | path_node_coverage | 0.000 |
| dev-28 | upstream | direct | refused | fully_correct | 0.000 |
| dev-41 | upstream | direct | refused | false_refusal | 1.000 |
| dev-41 | upstream | direct | refused | upstream_f1 | 0.000 |
| dev-41 | upstream | direct | refused | headline_f1 | 0.000 |
| dev-41 | upstream | direct | refused | path_node_coverage | 0.000 |
| dev-41 | upstream | direct | refused | fully_correct | 0.000 |
| dev-51 | downstream | all | refused | false_refusal | 1.000 |
| dev-51 | downstream | all | refused | columns_f1 | 0.000 |
| dev-51 | downstream | all | refused | models_f1 | 0.000 |
| dev-51 | downstream | all | refused | exposures_f1 | 0.000 |
| dev-51 | downstream | all | refused | headline_f1 | 0.000 |
| dev-51 | downstream | all | refused | fully_correct | 0.000 |
| dev-55 | downstream | all | clarification | columns_f1 | 0.000 |
| dev-55 | downstream | all | clarification | models_f1 | 0.000 |
| dev-55 | downstream | all | clarification | exposures_f1 | 0.000 |
| dev-55 | downstream | all | clarification | headline_f1 | 0.000 |
| dev-55 | downstream | all | clarification | fully_correct | 0.000 |
| dev-57 | downstream | all | refused | false_refusal | 1.000 |
| dev-57 | downstream | all | refused | columns_f1 | 0.000 |
| dev-57 | downstream | all | refused | models_f1 | 0.000 |
| dev-57 | downstream | all | refused | exposures_f1 | 0.000 |
| dev-57 | downstream | all | refused | headline_f1 | 0.000 |
| dev-57 | downstream | all | refused | fully_correct | 0.000 |
| dev-62 | downstream | all | refused | false_refusal | 1.000 |
| dev-62 | downstream | all | refused | columns_f1 | 0.000 |
| dev-62 | downstream | all | refused | models_f1 | 0.000 |
| dev-62 | downstream | all | refused | exposures_f1 | 0.000 |
| dev-62 | downstream | all | refused | headline_f1 | 0.000 |
| dev-62 | downstream | all | refused | fully_correct | 0.000 |
| dev-63 | downstream | all | refused | false_refusal | 1.000 |
| dev-63 | downstream | all | refused | columns_f1 | 0.000 |
| dev-63 | downstream | all | refused | models_f1 | 0.000 |
| dev-63 | downstream | all | refused | exposures_f1 | 0.000 |
| dev-63 | downstream | all | refused | headline_f1 | 0.000 |
| dev-63 | downstream | all | refused | fully_correct | 0.000 |
