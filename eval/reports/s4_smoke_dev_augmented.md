# S4 (augmented) on the 96 dev questions: S09 eval-smoke records, local qwen3:4b, hybrid off

metrics-design 1.1 · metrics.py 1.1.0 · dev.jsonl sha256 c265015ae72d · bootstrap 1000×, seed 20261019, CI only for n ≥ 10

Manifest: `{"hybrid": null, "model": "qwen3:4b-instruct-2507-q4_K_M", "note": "legacy: built by metrics.py from the records (pre-S10 run, no manifest)", "provider": "ollama", "record_count": 96, "records_file": "2026-10-18.jsonl", "system": "s4-qwen3-4b"}`

Complete: True

| metric | mean [95% CI] (n) |
|---|---|
| node_f1 | 0.464 [0.36, 0.57] (n=68) |
| trace_f1 | 0.536 [0.40, 0.67] (n=44) |
| impact_f1 | 0.332 [0.18, 0.51] (n=24) |
| upstream_f1 | 0.664 [0.51, 0.80] (n=29) |
| inputs_f1 | 0.289 [0.11, 0.49] (n=15) |
| inputs_f1_tolerant | 0.344 [0.13, 0.58] (n=15) |
| columns_f1 | 0.290 [0.14, 0.45] (n=24) |
| models_f1 | 0.447 [0.29, 0.62] (n=24) |
| exposures_f1 | 0.292 [0.12, 0.50] (n=24) |
| yesno_correct | 0.000 (n=6) |
| refusal_correct | 1.000 (n=9) |
| false_refusal | 0.230 [0.15, 0.32] (n=87) |
| chain_correct | 1.000 (n=2) |
| clarify_correct | 0.000 (n=1) |
| premise_rejected | 0.250 (n=4) |
| path_node_coverage | 0.517 [0.34, 0.69] (n=29) |
| fully_correct | 0.333 [0.24, 0.44] (n=84) |
| hallucination_rate | 0.000 [0.00, 0.00] (n=61) |
| has_hallucination | 0.000 [0.00, 0.00] (n=66) |
| citation_valid_answer | 0.924 [0.86, 0.98] (n=66) |
| citation_coverage | 1.000 [1.00, 1.00] (n=66) |

Citations checked 262, valid 259, r_ facts 4, model-level macro bucket 0, disagreements with R3 3.
Mentions removed by the negation rule: 13. CTE references: 0. Truncated payloads: dev-44, dev-67, dev-75.
Latency p50 5325.8 ms, p95 23329.1 ms over 77 uncached runs (19 cached, excluded). Tokens/question mean 2639.7083333333335, LLM calls/question mean 3.0625.

## node-set F1 by breakdown

**hop_bucket**: 1 0.500 [0.21, 0.79] (n=14); 2-3 0.562 [0.38, 0.73] (n=19); 4-5 0.576 [0.37, 0.79] (n=16); 6+ 0.275 [0.12, 0.43] (n=17); indirect-only 0.000 (n=2)

**wording**: description 0.000 (n=8); identifier 0.551 [0.41, 0.67] (n=35); name_words 0.548 [0.28, 0.80] (n=10); paraphrase 0.454 [0.20, 0.71] (n=15)

**type**: impact 0.332 [0.18, 0.51] (n=24); trace 0.536 [0.40, 0.67] (n=44)

**subtype**: ambiguous 0.667 (n=2); computed 0.303 [0.06, 0.58] (n=11); downstream 0.332 [0.18, 0.51] (n=24); false_premise 0.250 (n=4); multi_part 0.556 (n=3); upstream 0.677 [0.51, 0.83] (n=24)

**source**: hand 0.486 [0.27, 0.73] (n=14); template 0.397 [0.25, 0.54] (n=36); v0.2 0.580 [0.40, 0.75] (n=18)

**trap**: case_transformation 0.426 (n=6); deep_chain 0.275 [0.12, 0.43] (n=17); doc_injection 0.368 (n=2); exposures 0.285 [0.13, 0.47] (n=15); fan_in_aggregate 0.263 (n=5); join_key_only 0.429 (n=2); near_duplicate_names 0.538 (n=6); none 0.614 [0.42, 0.80] (n=23); rename_chain 0.883 (n=3); select_star 0.434 [0.26, 0.61] (n=22); stale_doc 0.000 (n=3); two_revenue_definitions 0.168 [0.02, 0.33] (n=10); union_all 0.395 (n=5); window_function 0.167 (n=2)

**linker_test_seen**: False 0.502 [0.39, 0.62] (n=54); True 0.316 [0.12, 0.52] (n=14)

## Per question (values below 1.0, and every miss)

| id | subtype | mode | kind | metric | value |
|---|---|---|---|---|---|
| dev-05 | upstream | direct | answered | upstream_f1 | 0.727 |
| dev-05 | upstream | direct | answered | headline_f1 | 0.727 |
| dev-05 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-05 | upstream | direct | answered | fully_correct | 0.000 |
| dev-06 | upstream | direct | answered | upstream_f1 | 0.600 |
| dev-06 | upstream | direct | answered | headline_f1 | 0.600 |
| dev-06 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-06 | upstream | direct | answered | fully_correct | 0.000 |
| dev-07 | downstream | all | answered | columns_f1 | 0.889 |
| dev-07 | downstream | all | answered | models_f1 | 0.889 |
| dev-07 | downstream | all | answered | headline_f1 | 0.889 |
| dev-07 | downstream | all | answered | fully_correct | 0.000 |
| dev-08 | downstream | all | answered | columns_f1 | 0.480 |
| dev-08 | downstream | all | answered | models_f1 | 0.741 |
| dev-08 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-08 | downstream | all | answered | headline_f1 | 0.480 |
| dev-08 | downstream | all | answered | fully_correct | 0.000 |
| dev-09 | downstream | all | answered | columns_f1 | 0.000 |
| dev-09 | downstream | all | answered | models_f1 | 0.000 |
| dev-09 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-09 | downstream | all | answered | headline_f1 | 0.000 |
| dev-09 | downstream | all | answered | fully_correct | 0.000 |
| dev-10 | yesno | all | answered | yesno_correct | 0.000 |
| dev-10 | yesno | all | answered | fully_correct | 0.000 |
| dev-10 | yesno | all | answered | citation_valid_answer | 0.000 |
| dev-11 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-11 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-11 | computed | direct | answered | headline_f1 | 0.000 |
| dev-11 | computed | direct | answered | fully_correct | 0.000 |
| dev-12 | computed | direct | answered | inputs_f1 | 0.667 |
| dev-12 | computed | direct | answered | headline_f1 | 0.667 |
| dev-12 | computed | direct | answered | fully_correct | 0.000 |
| dev-12 | computed | direct | answered | citation_valid_answer | 0.000 |
| dev-13 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-13 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-13 | computed | direct | answered | headline_f1 | 0.000 |
| dev-13 | computed | direct | answered | fully_correct | 0.000 |
| dev-15 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-15 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-15 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-15 | upstream | direct | answered | fully_correct | 0.000 |
| dev-16 | ambiguous | direct | answered | upstream_f1 | 0.333 |
| dev-16 | ambiguous | direct | answered | headline_f1 | 0.333 |
| dev-16 | ambiguous | direct | answered | path_node_coverage | 0.000 |
| dev-16 | ambiguous | direct | answered | fully_correct | 0.000 |
| dev-17 | false_premise | direct | answered | inputs_f1 | 0.500 |
| dev-17 | false_premise | direct | answered | inputs_f1_tolerant | 0.500 |
| dev-17 | false_premise | direct | answered | headline_f1 | 0.500 |
| dev-17 | false_premise | direct | answered | premise_rejected | 0.000 |
| dev-17 | false_premise | direct | answered | fully_correct | 0.000 |
| dev-18 | false_premise | direct | answered | inputs_f1 | 0.500 |
| dev-18 | false_premise | direct | answered | headline_f1 | 0.500 |
| dev-18 | false_premise | direct | answered | premise_rejected | 0.000 |
| dev-18 | false_premise | direct | answered | fully_correct | 0.000 |
| dev-20 | upstream | direct | answered | upstream_f1 | 0.750 |
| dev-20 | upstream | direct | answered | headline_f1 | 0.750 |
| dev-20 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-20 | upstream | direct | answered | fully_correct | 0.000 |
| dev-21 | upstream | direct | refused | false_refusal | 1.000 |
| dev-21 | upstream | direct | refused | upstream_f1 | 0.000 |
| dev-21 | upstream | direct | refused | headline_f1 | 0.000 |
| dev-21 | upstream | direct | refused | path_node_coverage | 0.000 |
| dev-21 | upstream | direct | refused | fully_correct | 0.000 |
| dev-23 | multi_part | direct | answered | upstream_f1 | 0.000 |
| dev-23 | multi_part | direct | answered | headline_f1 | 0.000 |
| dev-23 | multi_part | direct | answered | path_node_coverage | 0.000 |
| dev-23 | multi_part | direct | answered | fully_correct | 0.000 |
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
| dev-29 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-29 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-29 | computed | direct | answered | headline_f1 | 0.000 |
| dev-29 | computed | direct | answered | fully_correct | 0.000 |
| dev-30 | computed | direct | answered | inputs_f1 | 0.667 |
| dev-30 | computed | direct | answered | inputs_f1_tolerant | 0.667 |
| dev-30 | computed | direct | answered | headline_f1 | 0.667 |
| dev-30 | computed | direct | answered | fully_correct | 0.000 |
| dev-32 | multi_part | direct | answered | upstream_f1 | 0.667 |
| dev-32 | multi_part | direct | answered | headline_f1 | 0.667 |
| dev-32 | multi_part | direct | answered | path_node_coverage | 0.000 |
| dev-32 | multi_part | direct | answered | fully_correct | 0.000 |
| dev-35 | upstream | direct | answered | upstream_f1 | 0.857 |
| dev-35 | upstream | direct | answered | headline_f1 | 0.857 |
| dev-35 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-35 | upstream | direct | answered | fully_correct | 0.000 |
| dev-36 | upstream | direct | answered | upstream_f1 | 0.769 |
| dev-36 | upstream | direct | answered | headline_f1 | 0.769 |
| dev-36 | upstream | direct | answered | fully_correct | 0.000 |
| dev-38 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-38 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-38 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-38 | upstream | direct | answered | fully_correct | 0.000 |
| dev-41 | upstream | direct | refused | false_refusal | 1.000 |
| dev-41 | upstream | direct | refused | upstream_f1 | 0.000 |
| dev-41 | upstream | direct | refused | headline_f1 | 0.000 |
| dev-41 | upstream | direct | refused | path_node_coverage | 0.000 |
| dev-41 | upstream | direct | refused | fully_correct | 0.000 |
| dev-42 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-42 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-42 | computed | direct | answered | headline_f1 | 0.000 |
| dev-42 | computed | direct | answered | fully_correct | 0.000 |
| dev-42 | computed | direct | answered | citation_valid_answer | 0.000 |
| dev-43 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-43 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-43 | computed | direct | answered | headline_f1 | 0.000 |
| dev-43 | computed | direct | answered | fully_correct | 0.000 |
| dev-43 | computed | direct | answered | citation_valid_answer | 0.000 |
| dev-44 | upstream | direct | answered | upstream_f1 | 0.054 |
| dev-44 | upstream | direct | answered | headline_f1 | 0.054 |
| dev-44 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-44 | upstream | direct | answered | fully_correct | 0.000 |
| dev-45 | computed | direct | refused | false_refusal | 1.000 |
| dev-45 | computed | direct | refused | inputs_f1 | 0.000 |
| dev-45 | computed | direct | refused | inputs_f1_tolerant | 0.000 |
| dev-45 | computed | direct | refused | headline_f1 | 0.000 |
| dev-45 | computed | direct | refused | fully_correct | 0.000 |
| dev-46 | ambiguous | direct | refused | false_refusal | 1.000 |
| dev-46 | ambiguous | direct | refused | clarify_correct | 0.000 |
| dev-46 | ambiguous | direct | refused | fully_correct | 0.000 |
| dev-47 | upstream | direct | answered | upstream_f1 | 0.500 |
| dev-47 | upstream | direct | answered | headline_f1 | 0.500 |
| dev-47 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-47 | upstream | direct | answered | fully_correct | 0.000 |
| dev-49 | false_premise | direct | answered | inputs_f1 | 0.000 |
| dev-49 | false_premise | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-49 | false_premise | direct | answered | headline_f1 | 0.000 |
| dev-49 | false_premise | direct | answered | fully_correct | 0.000 |
| dev-50 | false_premise | direct | answered | inputs_f1 | 0.000 |
| dev-50 | false_premise | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-50 | false_premise | direct | answered | headline_f1 | 0.000 |
| dev-50 | false_premise | direct | answered | premise_rejected | 0.000 |
| dev-50 | false_premise | direct | answered | fully_correct | 0.000 |
| dev-51 | downstream | all | refused | false_refusal | 1.000 |
| dev-51 | downstream | all | refused | columns_f1 | 0.000 |
| dev-51 | downstream | all | refused | models_f1 | 0.000 |
| dev-51 | downstream | all | refused | exposures_f1 | 0.000 |
| dev-51 | downstream | all | refused | headline_f1 | 0.000 |
| dev-51 | downstream | all | refused | fully_correct | 0.000 |
| dev-52 | downstream | all | answered | columns_f1 | 0.000 |
| dev-52 | downstream | all | answered | models_f1 | 0.400 |
| dev-52 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-52 | downstream | all | answered | headline_f1 | 0.000 |
| dev-52 | downstream | all | answered | fully_correct | 0.000 |
| dev-53 | downstream | all | answered | columns_f1 | 0.000 |
| dev-53 | downstream | all | answered | models_f1 | 0.222 |
| dev-53 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-53 | downstream | all | answered | headline_f1 | 0.000 |
| dev-53 | downstream | all | answered | fully_correct | 0.000 |
| dev-55 | downstream | all | clarification | columns_f1 | 0.000 |
| dev-55 | downstream | all | clarification | models_f1 | 0.000 |
| dev-55 | downstream | all | clarification | exposures_f1 | 0.000 |
| dev-55 | downstream | all | clarification | headline_f1 | 0.000 |
| dev-55 | downstream | all | clarification | fully_correct | 0.000 |
| dev-56 | downstream | all | answered | columns_f1 | 0.000 |
| dev-56 | downstream | all | answered | models_f1 | 0.667 |
| dev-56 | downstream | all | answered | headline_f1 | 0.000 |
| dev-56 | downstream | all | answered | fully_correct | 0.000 |
| dev-57 | downstream | all | refused | false_refusal | 1.000 |
| dev-57 | downstream | all | refused | columns_f1 | 0.000 |
| dev-57 | downstream | all | refused | models_f1 | 0.000 |
| dev-57 | downstream | all | refused | exposures_f1 | 0.000 |
| dev-57 | downstream | all | refused | headline_f1 | 0.000 |
| dev-57 | downstream | all | refused | fully_correct | 0.000 |
| dev-58 | downstream | all | answered | columns_f1 | 0.737 |
| dev-58 | downstream | all | answered | headline_f1 | 0.737 |
| dev-58 | downstream | all | answered | fully_correct | 0.000 |
| dev-59 | downstream | all | answered | columns_f1 | 0.800 |
| dev-59 | downstream | all | answered | models_f1 | 0.800 |
| dev-59 | downstream | all | answered | headline_f1 | 0.800 |
| dev-59 | downstream | all | answered | fully_correct | 0.000 |
| dev-60 | downstream | all | answered | columns_f1 | 0.000 |
| dev-60 | downstream | all | answered | models_f1 | 0.600 |
| dev-60 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-60 | downstream | all | answered | headline_f1 | 0.000 |
| dev-60 | downstream | all | answered | fully_correct | 0.000 |
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
| dev-64 | downstream | all | answered | columns_f1 | 0.000 |
| dev-64 | downstream | all | answered | models_f1 | 0.533 |
| dev-65 | downstream | all | answered | columns_f1 | 0.522 |
| dev-65 | downstream | all | answered | models_f1 | 0.923 |
| dev-65 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-65 | downstream | all | answered | headline_f1 | 0.522 |
| dev-65 | downstream | all | answered | fully_correct | 0.000 |
| dev-66 | downstream | all | refused | false_refusal | 1.000 |
| dev-66 | downstream | all | refused | columns_f1 | 0.000 |
| dev-66 | downstream | all | refused | models_f1 | 0.000 |
| dev-66 | downstream | all | refused | exposures_f1 | 0.000 |
| dev-66 | downstream | all | refused | headline_f1 | 0.000 |
| dev-66 | downstream | all | refused | fully_correct | 0.000 |
| dev-67 | downstream | all | answered | columns_f1 | 0.750 |
| dev-67 | downstream | all | answered | models_f1 | 0.833 |
| dev-67 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-67 | downstream | all | answered | headline_f1 | 0.750 |
| dev-67 | downstream | all | answered | fully_correct | 0.000 |
| dev-68 | downstream | all | answered | columns_f1 | 0.649 |
| dev-68 | downstream | all | answered | models_f1 | 0.857 |
| dev-68 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-68 | downstream | all | answered | headline_f1 | 0.649 |
| dev-68 | downstream | all | answered | fully_correct | 0.000 |
| dev-69 | downstream | all | answered | columns_f1 | 0.143 |
| dev-69 | downstream | all | answered | models_f1 | 0.261 |
| dev-69 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-69 | downstream | all | answered | headline_f1 | 0.143 |
| dev-69 | downstream | all | answered | fully_correct | 0.000 |
| dev-70 | downstream | all | refused | false_refusal | 1.000 |
| dev-70 | downstream | all | refused | columns_f1 | 0.000 |
| dev-70 | downstream | all | refused | models_f1 | 0.000 |
| dev-70 | downstream | all | refused | exposures_f1 | 0.000 |
| dev-70 | downstream | all | refused | headline_f1 | 0.000 |
| dev-70 | downstream | all | refused | fully_correct | 0.000 |
| dev-71 | downstream | all | refused | false_refusal | 1.000 |
| dev-71 | downstream | all | refused | columns_f1 | 0.000 |
| dev-71 | downstream | all | refused | models_f1 | 0.000 |
| dev-71 | downstream | all | refused | exposures_f1 | 0.000 |
| dev-71 | downstream | all | refused | headline_f1 | 0.000 |
| dev-71 | downstream | all | refused | fully_correct | 0.000 |
| dev-72 | yesno | all | answered | yesno_correct | 0.000 |
| dev-72 | yesno | all | answered | fully_correct | 0.000 |
| dev-73 | yesno | all | answered | yesno_correct | 0.000 |
| dev-73 | yesno | all | answered | fully_correct | 0.000 |
| dev-74 | yesno | all | answered | yesno_correct | 0.000 |
| dev-74 | yesno | all | answered | fully_correct | 0.000 |
| dev-75 | yesno | all | answered | yesno_correct | 0.000 |
| dev-75 | yesno | all | answered | fully_correct | 0.000 |
| dev-76 | yesno | all | answered | yesno_correct | 0.000 |
| dev-76 | yesno | all | answered | fully_correct | 0.000 |
| dev-76 | yesno | all | answered | citation_valid_answer | 0.000 |
| dev-78 | meaning | None | refused | false_refusal | 1.000 |
| dev-80 | meaning | None | refused | false_refusal | 1.000 |
| dev-82 | meaning | None | refused | false_refusal | 1.000 |
| dev-84 | meaning | None | refused | false_refusal | 1.000 |
| dev-85 | meaning | None | refused | false_refusal | 1.000 |
| dev-86 | meaning | None | refused | false_refusal | 1.000 |
| dev-87 | meaning | None | refused | false_refusal | 1.000 |
