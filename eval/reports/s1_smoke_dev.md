# S1 (vector RAG, local qwen3:4b) on the 96 dev questions

metrics-design 1.1 · metrics.py 1.2.0 · dev.jsonl sha256 c265015ae72d · bootstrap 1000×, seed 20261019, CI only for n ≥ 10

Manifest: `{"allow_cloud": false, "budget": {"cap": 3000, "fill_rule": "skip_and_pack", "k_ceiling": null, "overhead_est_tokens": {"max": 679, "min": 642}, "repair_reserve": 200}, "date": "2026-10-20", "git_commit": "f0efd336c0302cc44d45088962d062b1a5b4b6bb", "hybrid": true, "metrics_versions": {"design": "1.1", "metrics": "1.2.0"}, "model": "qwen3:4b-instruct-2507-q4_K_M", "note": "S1 vector RAG: hybrid BM25 + dense + RRF on project text; no graph, no validator", "params": {"num_ctx": 8192, "temperature": 0, "think": false}, "prompt_sha256": {"budget_rule": "c2ec079e87e8ef5e99ce68df2e408da841791621e89060cec69df944269cd1a9", "clarification": "40fd7a42eff2255149fcebd964d1677664232bb30c3eb6dcc8a1ea38251efa92", "evidence_rule": "56973cf48a60bd249c3282cb83e097b9d6c4549b6622100206286f1fc378c6e4", "repair": "cc417eb2aa5ab698cc0ed1052710865c4448b9b5e8feaab42ad8133b809bca9b", "schema": "6036435098ff605e8903f6fd711ee099975339141c3d9d7c1306c957d9f3f65d", "system": "fb820558a6542b1d2207d8b1f7d7ac33bf3e4c2646419d60435cfa698ddbe847", "user_template": "b85d5465fc9c921750ec044cad93fb8fbcfbc0885a9ff257777f69054dd24445"}, "provider": "ollama", "questions_file": "eval/questions/dev.jsonl", "questions_sha256": "c265015ae72d62d4e2865493a50fba408e3e7c3ff4afafd2a5f992e425c5fe11", "record_count": 96, "records_file": "s1-qwen3-4b-instruct-2507-q4-k-m-dev.jsonl", "required": ["dev-01", "dev-02", "dev-03", "dev-04", "dev-05", "dev-06", "dev-07", "dev-08", "dev-09", "dev-10", "dev-11", "dev-12", "dev-13", "dev-14", "dev-15", "dev-16", "dev-17", "dev-18", "dev-19", "dev-20", "dev-21", "dev-22", "dev-23", "dev-24", "dev-25", "dev-26", "dev-27", "dev-28", "dev-29", "dev-30", "dev-31", "dev-32", "dev-33", "dev-34", "dev-35", "dev-36", "dev-37", "dev-38", "dev-39", "dev-40", "dev-41", "dev-42", "dev-43", "dev-44", "dev-45", "dev-46", "dev-47", "dev-48", "dev-49", "dev-50", "dev-51", "dev-52", "dev-53", "dev-54", "dev-55", "dev-56", "dev-57", "dev-58", "dev-59", "dev-60", "dev-61", "dev-62", "dev-63", "dev-64", "dev-65", "dev-66", "dev-67", "dev-68", "dev-69", "dev-70", "dev-71", "dev-72", "dev-73", "dev-74", "dev-75", "dev-76", "dev-77", "dev-78", "dev-79", "dev-80", "dev-81", "dev-82", "dev-83", "dev-84", "dev-85", "dev-86", "dev-87", "dev-88", "dev-89", "dev-90", "dev-91", "dev-92", "dev-93", "dev-94", "dev-95", "dev-96"], "retrieval": {"candidates": 200, "citation_rule": "dlens.retrieval.citation.chunk_citation (seed card: CSV header)", "embedder": {"max_length": 512, "model": "BAAI/bge-small-en-v1.5@5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", "runtime": "onnxruntime 1.31.0 + tokenizers 0.23.2", "threads": 4}, "index_key": {"catalog_sha256": "54cbfae7c11700dba088437609bd472bb52e8089e3cba2206ff82c033977ed64", "chunker_version": 1, "chunks_sha256": "bae30993fa2eabd067d99cd6a08478e702bee82fbb983de266f70f88bfcebbe1", "files": {"models/intermediate/int_campaign_spend_daily.sql": "f59e89b4c741483bcb233ef7d084b8007fb61c3952000b0fcdd98e6e730eda69", "models/intermediate/int_customer_order_history.sql": "bf36904666990574128c1bb0fc7f3b0de81d30a38d4a580175ea452609597b6a", "models/intermediate/int_customer_sessions.sql": "3933803baaf3b4adfe334e18a6bac5b0d1f34d28a85149e915d98c4ec8c01628", "models/intermediate/int_inventory_daily.sql": "f729c060e2ac7acfbe4287b4fd753196bba8d0221de873e9b837704c2930596c", "models/intermediate/int_order_adjustments.sql": "902e0001d198460e73423530a288d639493560a439c478d49f672d8daf104716", "models/intermediate/int_order_attribution.sql": "c6a7c17270cc67ef0dfacacca83b2113d1b91efea4eab3783b5cac486f5dcc63", "models/intermediate/int_order_financials.sql": "f87fe1d5f145e17f28d4b63f42f0b8787aa24589c4b243e1a0d9a7db9f3dbe7e", "models/intermediate/int_order_item_margins.sql": "1d6313e0831e15a0034dfe9d9dea42169f707151faa343ff66727cc5ff1f0514", "models/intermediate/int_order_items_enriched.sql": "f13769efde44684e5c7a5dd3509f5a747331451ef52d068e96d64eb208822fbc", "models/intermediate/int_order_profit.sql": "6ce07f7c89891b6e8d2d15fc35892a3a22de16cce058b90b1b549e6a2cda9356", "models/intermediate/int_order_promotions.sql": "eacdda1b954aab426c9c6cc93c95f7e57447e534a63c3f05c6400e798479b6d6", "models/intermediate/int_order_shipping.sql": "134ad7a3913cbc62b8bfd498125f4304c5e1fbea12664bf7cb26bfb69b16c313", "models/intermediate/int_orders_enriched.sql": "a249025eb3af4f124b67018ff74725655b195b6ea40aae4820fef0d39cb28c31", "models/intermediate/int_payment_events.sql": "9ea611afbac88a1a99a6611563e5ae10755f1fef29407d7320c00fe52d6dbcc6", "models/intermediate/int_product_costs_current.sql": "9782890ad4ecde9e4f4761bbba58bdf57e88b83db5d29a8c1e77dda73e149b3f", "models/intermediate/int_sessions_daily.sql": "26e5a6ff5199f24233eb20bfa72321fac7303f3eec3c239c18777a1f1466ef38", "models/intermediate/int_shipments_enriched.sql": "fbebf6dd30ee5f1fe3fe298b97c323b3523d73de3574fe5f0caa8b19db2c6426", "models/intermediate/int_web_sessions_clean.sql": "646f00f12bfe5bca7ebb1dadd4017d483f342bcb996446cafb0e0b295d7ed1b4", "models/intermediate/schema.yml": "b5acf1351e86aeaa6826c7f9a8cc473e67d4f8103bb73e8813deebe48c775329", "models/marts/dim_customer_rfm.sql": "7e9fceb12de4b25cd8f13405f6ef6736c0d44bd13e976614595482e9dfb92e2c", "models/marts/dim_customer_segments.sql": "10f8b2c63c049e3e043758504cd0a03282c289c5b9f42d21d72c0ea22e466d1e", "models/marts/dim_customers.sql": "b2bcb1f5ba71a2b4ce09ae22beaa5756c24eb30301f6490865d82ac8b43c6297", "models/marts/exposures.yml": "2c089ad99c3e482ac5baeeb16a465552506775677e17d09cd09bf4fe3c7f96b7", "models/marts/fct_channel_performance_monthly.sql": "7cca97d3f5efba9c2f88a3ff463c66c047792516b23c6ffd714683a32ad0ca33", "models/marts/fct_customer_cohorts.sql": "52faa6ef3474fdec297547f56a320e3aa51373253dc4f1650334b04d45747282", "models/marts/fct_customer_leaderboard.sql": "ac8a414b7d949a58c5f55df28c44a00b47ac32c730f1149b0aff633f0bb1245d", "models/marts/fct_daily_revenue.sql": "a92d3f6e3d228028336c4f5fa5f12f5540c08e6ed4f747f1db2f42f1a2a85dbe", "models/marts/fct_inventory_status.sql": "6bd692ba035f600133f9f590302e2c640933a36afcc670475a58b3f19102f877", "models/marts/fct_marketing_attribution.sql": "ce0d9f900cc9f54026d23af5ef9d8acd18016e543a2f8fa70a38c5b61ce8306d", "models/marts/fct_monthly_finance.sql": "0b1091e1d7180c13b1c44ad2cf40435f021c6584bcd0ad0484f8af43967a512d", "models/marts/fct_order_margins.sql": "80b16c3b1af49bc574b96eb49f1285d5010976e08e22dddc57e04b64c662f289", "models/marts/fct_orders.sql": "5392f65828e0893bd8a759ebda1defd623bc796fd83cc088202ef41a4a80f8cf", "models/marts/fct_payment_events.sql": "c278bc5c9642d93de83291bd85f62e5677cf8272c394ab12a576cf69cb69d139", "models/marts/fct_product_performance.sql": "5f1e1c20c40235d994d6a1ad6581d5675bae7d5e785b9ba1ba455c62a9811ad2", "models/marts/fct_segment_monthly.sql": "79db60cd02ff81cbe662bbcd73773c08193a334a5f38a4d11028acc290b2b438", "models/marts/fct_shipping_performance.sql": "d441caf9df54015d1f8119e2cb0b71fa7ff0aa551d31559e538f120d60e15e94", "models/marts/fct_top_products.sql": "339a3db4b2a0101d1998691b56290ae6ed10066261574606e4c691c9986dde30", "models/marts/schema.yml": "59a706b650dccb34165fde1fbc099e7d15c29961dff87447230b8f06a9374850", "models/staging/schema.yml": "f74782556996ae4e0cce82394be3b1e38afd60bf071281ad6f68c843ca063a82", "models/staging/stg_customers.sql": "8e429cf1208c62cce0a1f9618c0503b26234d415a0104b7c3c8a7f1b3e8580f5", "models/staging/stg_inventory_snapshots.sql": "a08b869d4f379d81e7097a5cec6d86475ce1d9f49031b0a50cf8f86d77c84a4f", "models/staging/stg_marketing_spend.sql": "3cd9022ebdbfa1c4a9b7abbc0ec6779bc6427e1feff80eca8e9a4f01af15a029", "models/staging/stg_order_items.sql": "5f9811dcf55ca6090f76bb3d95ccb98f6615f3d04b67a96b84d1d7b114008666", "models/staging/stg_order_promotions.sql": "8214e1daf417e046ab426f04553e9dd81dc7c69a4a5a838f81ca9c1d8061e3ff", "models/staging/stg_orders.sql": "09e70909ae9058c53ba91e5d84817b437b7364967a47f7e1eeb45f30c46ae0ee", "models/staging/stg_payments.sql": "8a02be577cd8c8e208645fbbbcdac366b92728327f440c485419317ee473e5a6", "models/staging/stg_product_costs.sql": "418adbe63ab0c624e36caceeaf6f734385a97c007d1faed0df36f04ad1dd0818", "models/staging/stg_products.sql": "c0eebdfc6607500bdc1e0cd3588dae7d701f40b6b0449ca6e209a7b7a25e2581", "models/staging/stg_promotions.sql": "913054da337d964c71865c5fdd96dbbadf571e0e19af8c40601f934e08a07752", "models/staging/stg_refunds.sql": "6bf7f74d662d571c5b190711f70059660e763470b161b35cf714779abbf84207", "models/staging/stg_shipments.sql": "b4d775feea457a694d898ec093eda1fb95754f6b5449aeb808bdda2926b48c00", "models/staging/stg_suppliers.sql": "e6f22fc55c8fcea2be790f8717d528d61700c2faa06767d29f23e76f9b86033e", "models/staging/stg_web_sessions.sql": "51327c6e9d56aac2a8f15ab3f25e814a32fbcfae47fdda6962e37c07ab167844", "seeds/raw_customers.csv": "0e20a042e45e47a665e821522db1f0d0c03663b5e78a2db7716e8020012e4f19", "seeds/raw_inventory_snapshots.csv": "9a6b108fb71a5bafe42c0048ff19fcaaa63bc161cb75758f6b19c7e5b9f5799f", "seeds/raw_marketing_spend.csv": "14945da7bd60feb1fedbfbc7bb34426724f8fe9bed0add6bd579bd4e7c781cc9", "seeds/raw_order_items.csv": "b85c0f7ef0d34a9dc4697bec0e34bb13dd1c1b612ceb18e4c27531e9c12b0cd9", "seeds/raw_order_promotions.csv": "124ff050be1f33c6102cc550fc6b51a453d368d014238a785354994721de9dd5", "seeds/raw_orders.csv": "d6a501eb7a3d89d4525a80c10ce0a5c52e3161da022912fc2682dad871d6b360", "seeds/raw_payments.csv": "b1beecf2939cf8edf2013346ea78697d64a87cfbbfb7a2b97438308871162ade", "seeds/raw_product_costs.csv": "5245c3657accd0a80fdf227af37d171f2392312edde9285a4314b9d0b93e8d45", "seeds/raw_products.csv": "794253c80c200d19a24ea104dea3b2fcec0a78db00232e7d7e2aaf4d571601a5", "seeds/raw_promotions.csv": "46f90baab8bf7cadc0d9011ce2bf45cf114e61b8158cd151d2d930aa7383543b", "seeds/raw_refunds.csv": "46d7eb7cddc8b55c02abe87c76150f9488d79799521968dc50cd819cd9ca16cc", "seeds/raw_shipments.csv": "d299caa16fd556ba739c2b3cbb1be6d4377d24f00618ec753506fae058ba6b6f", "seeds/raw_suppliers.csv": "32723ec842e3d65dca3c4c5b28ce8e861849c1426db0e0b223316805a0efebc2", "seeds/raw_web_sessions.csv": "7e88b968907241bfc96f4cb70510499afc1ce04ab3d52ffcd328e362232bb818"}, "format": 1, "graph_sha256": "8360a447c81e80e8d8a3d177ad2854922de1feaba9209b163579e7cd668f60d1", "manifest_sha256": "36df1fdabc162fbad27eaf9c5ab234085723e003e25b556b7e32f7f4013a44df", "max_length": 512, "model": "BAAI/bge-small-en-v1.5@5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", "runtime": "onnxruntime 1.31.0 + tokenizers 0.23.2", "threads": 4}, "index_status": "index reused", "kinds": "all (model, column, doc)", "mode": "hybrid", "per_list_depth": 100, "query": "raw question text", "rrf_k": 60}, "system": "s1-qwen3-4b-instruct-2507-q4-k-m", "view": "validated"}`

Complete: True

| metric | mean [95% CI] (n) |
|---|---|
| node_f1 | 0.248 [0.17, 0.33] (n=68) |
| trace_f1 | 0.303 [0.19, 0.41] (n=44) |
| impact_f1 | 0.148 [0.07, 0.24] (n=24) |
| upstream_f1 | 0.361 [0.22, 0.49] (n=29) |
| inputs_f1 | 0.189 [0.04, 0.39] (n=15) |
| inputs_f1_tolerant | 0.231 [0.05, 0.46] (n=15) |
| columns_f1 | 0.154 [0.08, 0.25] (n=24) |
| models_f1 | 0.468 [0.36, 0.56] (n=24) |
| exposures_f1 | 0.375 [0.17, 0.54] (n=24) |
| yesno_correct | 0.500 (n=6) |
| refusal_correct | 0.556 (n=9) |
| false_refusal | 0.011 [0.00, 0.05] (n=87) |
| chain_correct | 0.000 (n=2) |
| clarify_correct | 0.000 (n=1) |
| premise_rejected | 0.250 (n=4) |
| path_node_coverage | 0.207 [0.07, 0.34] (n=29) |
| fully_correct | 0.179 [0.11, 0.26] (n=84) |
| hallucination_rate | 0.000 [0.00, 0.00] (n=76) |
| has_hallucination | 0.000 [0.00, 0.00] (n=90) |
| citation_valid_answer | 0.322 [0.22, 0.42] (n=90) |
| citation_coverage | 1.000 [1.00, 1.00] (n=90) |

Citations checked 282, valid 132, r_ facts 0, model-level macro bucket 0, disagreements with R3 0.
Mentions removed by the negation rule: 4. CTE references: 2. Truncated payloads: none.
Latency p50 7727.6 ms, p95 14699.8 ms over 95 uncached runs (1 cached, excluded). Tokens/question mean 2329.3958333333335, LLM calls/question mean 1.0.

## node-set F1 by breakdown

**hop_bucket**: 1 0.567 [0.33, 0.80] (n=14); 2-3 0.199 [0.07, 0.36] (n=19); 4-5 0.184 [0.09, 0.28] (n=16); 6+ 0.102 [0.04, 0.19] (n=17); indirect-only 0.231 (n=2)

**wording**: description 0.101 (n=8); identifier 0.327 [0.21, 0.44] (n=35); name_words 0.252 [0.06, 0.49] (n=10); paraphrase 0.140 [0.03, 0.29] (n=15)

**type**: impact 0.148 [0.07, 0.24] (n=24); trace 0.303 [0.19, 0.41] (n=44)

**subtype**: ambiguous 0.000 (n=2); computed 0.212 [0.00, 0.42] (n=11); downstream 0.148 [0.07, 0.24] (n=24); false_premise 0.125 (n=4); multi_part 0.444 (n=3); upstream 0.381 [0.23, 0.55] (n=24)

**source**: hand 0.150 [0.03, 0.32] (n=14); template 0.274 [0.16, 0.38] (n=36); v0.2 0.272 [0.13, 0.45] (n=18)

**trap**: case_transformation 0.095 (n=6); deep_chain 0.102 [0.04, 0.19] (n=17); doc_injection 0.200 (n=2); exposures 0.133 [0.07, 0.21] (n=15); fan_in_aggregate 0.133 (n=5); join_key_only 0.431 (n=2); near_duplicate_names 0.230 (n=6); none 0.422 [0.25, 0.60] (n=23); rename_chain 0.111 (n=3); select_star 0.181 [0.08, 0.29] (n=22); stale_doc 0.356 (n=3); two_revenue_definitions 0.146 [0.03, 0.27] (n=10); union_all 0.367 (n=5); window_function 0.088 (n=2)

**linker_test_seen**: False 0.293 [0.20, 0.38] (n=54); True 0.074 [0.02, 0.14] (n=14)

## Per question (values below 1.0, and every miss)

| id | subtype | mode | kind | metric | value |
|---|---|---|---|---|---|
| dev-03 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-03 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-03 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-03 | upstream | direct | answered | fully_correct | 0.000 |
| dev-04 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-04 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-04 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-04 | upstream | direct | answered | fully_correct | 0.000 |
| dev-05 | upstream | direct | answered | upstream_f1 | 0.444 |
| dev-05 | upstream | direct | answered | headline_f1 | 0.444 |
| dev-05 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-05 | upstream | direct | answered | fully_correct | 0.000 |
| dev-05 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-06 | upstream | direct | answered | upstream_f1 | 0.133 |
| dev-06 | upstream | direct | answered | headline_f1 | 0.133 |
| dev-06 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-06 | upstream | direct | answered | fully_correct | 0.000 |
| dev-06 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-07 | downstream | all | answered | columns_f1 | 0.000 |
| dev-07 | downstream | all | answered | models_f1 | 0.750 |
| dev-07 | downstream | all | answered | headline_f1 | 0.000 |
| dev-07 | downstream | all | answered | fully_correct | 0.000 |
| dev-07 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-08 | downstream | all | answered | columns_f1 | 0.222 |
| dev-08 | downstream | all | answered | models_f1 | 0.381 |
| dev-08 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-08 | downstream | all | answered | headline_f1 | 0.222 |
| dev-08 | downstream | all | answered | fully_correct | 0.000 |
| dev-08 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-09 | downstream | all | answered | columns_f1 | 0.176 |
| dev-09 | downstream | all | answered | models_f1 | 0.400 |
| dev-09 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-09 | downstream | all | answered | headline_f1 | 0.176 |
| dev-09 | downstream | all | answered | fully_correct | 0.000 |
| dev-09 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-11 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-11 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-11 | computed | direct | answered | headline_f1 | 0.000 |
| dev-11 | computed | direct | answered | fully_correct | 0.000 |
| dev-11 | computed | direct | answered | citation_valid_answer | 0.000 |
| dev-12 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-12 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-12 | computed | direct | answered | headline_f1 | 0.000 |
| dev-12 | computed | direct | answered | fully_correct | 0.000 |
| dev-13 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-13 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-13 | computed | direct | answered | headline_f1 | 0.000 |
| dev-13 | computed | direct | answered | fully_correct | 0.000 |
| dev-14 | upstream | direct | answered | upstream_f1 | 0.667 |
| dev-14 | upstream | direct | answered | headline_f1 | 0.667 |
| dev-14 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-14 | upstream | direct | answered | fully_correct | 0.000 |
| dev-15 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-15 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-15 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-15 | upstream | direct | answered | fully_correct | 0.000 |
| dev-15 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-16 | ambiguous | direct | answered | chain_correct | 0.000 |
| dev-16 | ambiguous | direct | answered | upstream_f1 | 0.000 |
| dev-16 | ambiguous | direct | answered | headline_f1 | 0.000 |
| dev-16 | ambiguous | direct | answered | path_node_coverage | 0.000 |
| dev-16 | ambiguous | direct | answered | fully_correct | 0.000 |
| dev-16 | ambiguous | direct | answered | citation_valid_answer | 0.000 |
| dev-17 | false_premise | direct | refused | false_refusal | 1.000 |
| dev-17 | false_premise | direct | refused | inputs_f1 | 0.000 |
| dev-17 | false_premise | direct | refused | inputs_f1_tolerant | 0.000 |
| dev-17 | false_premise | direct | refused | headline_f1 | 0.000 |
| dev-17 | false_premise | direct | refused | premise_rejected | 0.000 |
| dev-17 | false_premise | direct | refused | fully_correct | 0.000 |
| dev-18 | false_premise | direct | answered | inputs_f1 | 0.500 |
| dev-18 | false_premise | direct | answered | inputs_f1_tolerant | 0.800 |
| dev-18 | false_premise | direct | answered | headline_f1 | 0.500 |
| dev-18 | false_premise | direct | answered | premise_rejected | 0.000 |
| dev-18 | false_premise | direct | answered | fully_correct | 0.000 |
| dev-18 | false_premise | direct | answered | citation_valid_answer | 0.000 |
| dev-20 | upstream | direct | answered | upstream_f1 | 0.750 |
| dev-20 | upstream | direct | answered | headline_f1 | 0.750 |
| dev-20 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-20 | upstream | direct | answered | fully_correct | 0.000 |
| dev-20 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-21 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-21 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-21 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-21 | upstream | direct | answered | fully_correct | 0.000 |
| dev-21 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-24 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-27 | computed | direct | answered | inputs_f1 | 0.667 |
| dev-27 | computed | direct | answered | inputs_f1_tolerant | 0.667 |
| dev-27 | computed | direct | answered | headline_f1 | 0.667 |
| dev-27 | computed | direct | answered | fully_correct | 0.000 |
| dev-27 | computed | direct | answered | citation_valid_answer | 0.000 |
| dev-28 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-28 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-28 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-28 | upstream | direct | answered | fully_correct | 0.000 |
| dev-28 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-29 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-29 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-29 | computed | direct | answered | headline_f1 | 0.000 |
| dev-29 | computed | direct | answered | fully_correct | 0.000 |
| dev-29 | computed | direct | answered | citation_valid_answer | 0.000 |
| dev-30 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-30 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-30 | computed | direct | answered | headline_f1 | 0.000 |
| dev-30 | computed | direct | answered | fully_correct | 0.000 |
| dev-31 | ambiguous | direct | answered | chain_correct | 0.000 |
| dev-31 | ambiguous | direct | answered | upstream_f1 | 0.000 |
| dev-31 | ambiguous | direct | answered | headline_f1 | 0.000 |
| dev-31 | ambiguous | direct | answered | path_node_coverage | 0.000 |
| dev-31 | ambiguous | direct | answered | fully_correct | 0.000 |
| dev-32 | multi_part | direct | answered | upstream_f1 | 0.000 |
| dev-32 | multi_part | direct | answered | headline_f1 | 0.000 |
| dev-32 | multi_part | direct | answered | path_node_coverage | 0.000 |
| dev-32 | multi_part | direct | answered | fully_correct | 0.000 |
| dev-33 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-33 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-33 | computed | direct | answered | headline_f1 | 0.000 |
| dev-33 | computed | direct | answered | fully_correct | 0.000 |
| dev-33 | computed | direct | answered | citation_valid_answer | 0.000 |
| dev-34 | multi_part | direct | answered | upstream_f1 | 0.333 |
| dev-34 | multi_part | direct | answered | headline_f1 | 0.333 |
| dev-34 | multi_part | direct | answered | path_node_coverage | 0.000 |
| dev-34 | multi_part | direct | answered | fully_correct | 0.000 |
| dev-35 | upstream | direct | answered | upstream_f1 | 0.400 |
| dev-35 | upstream | direct | answered | headline_f1 | 0.400 |
| dev-35 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-35 | upstream | direct | answered | fully_correct | 0.000 |
| dev-36 | upstream | direct | answered | upstream_f1 | 0.222 |
| dev-36 | upstream | direct | answered | headline_f1 | 0.222 |
| dev-36 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-36 | upstream | direct | answered | fully_correct | 0.000 |
| dev-37 | upstream | direct | answered | upstream_f1 | 0.571 |
| dev-37 | upstream | direct | answered | headline_f1 | 0.571 |
| dev-37 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-37 | upstream | direct | answered | fully_correct | 0.000 |
| dev-37 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-38 | upstream | direct | answered | upstream_f1 | 0.286 |
| dev-38 | upstream | direct | answered | headline_f1 | 0.286 |
| dev-38 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-38 | upstream | direct | answered | fully_correct | 0.000 |
| dev-38 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-39 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-39 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-39 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-39 | upstream | direct | answered | fully_correct | 0.000 |
| dev-39 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-40 | upstream | direct | answered | upstream_f1 | 0.333 |
| dev-40 | upstream | direct | answered | headline_f1 | 0.333 |
| dev-40 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-40 | upstream | direct | answered | fully_correct | 0.000 |
| dev-41 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-41 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-41 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-41 | upstream | direct | answered | fully_correct | 0.000 |
| dev-41 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-42 | computed | direct | answered | inputs_f1 | 0.667 |
| dev-42 | computed | direct | answered | headline_f1 | 0.667 |
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
| dev-44 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-45 | computed | direct | answered | inputs_f1 | 0.000 |
| dev-45 | computed | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-45 | computed | direct | answered | headline_f1 | 0.000 |
| dev-45 | computed | direct | answered | fully_correct | 0.000 |
| dev-45 | computed | direct | answered | citation_valid_answer | 0.000 |
| dev-46 | ambiguous | direct | answered | clarify_correct | 0.000 |
| dev-46 | ambiguous | direct | answered | fully_correct | 0.000 |
| dev-46 | ambiguous | direct | answered | citation_valid_answer | 0.000 |
| dev-47 | upstream | direct | answered | upstream_f1 | 0.000 |
| dev-47 | upstream | direct | answered | headline_f1 | 0.000 |
| dev-47 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-47 | upstream | direct | answered | fully_correct | 0.000 |
| dev-47 | upstream | direct | answered | citation_valid_answer | 0.000 |
| dev-48 | upstream | direct | answered | upstream_f1 | 0.286 |
| dev-48 | upstream | direct | answered | headline_f1 | 0.286 |
| dev-48 | upstream | direct | answered | path_node_coverage | 0.000 |
| dev-48 | upstream | direct | answered | fully_correct | 0.000 |
| dev-49 | false_premise | direct | answered | inputs_f1 | 0.000 |
| dev-49 | false_premise | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-49 | false_premise | direct | answered | headline_f1 | 0.000 |
| dev-49 | false_premise | direct | answered | premise_rejected | 0.000 |
| dev-49 | false_premise | direct | answered | fully_correct | 0.000 |
| dev-49 | false_premise | direct | answered | citation_valid_answer | 0.000 |
| dev-50 | false_premise | direct | answered | inputs_f1 | 0.000 |
| dev-50 | false_premise | direct | answered | inputs_f1_tolerant | 0.000 |
| dev-50 | false_premise | direct | answered | headline_f1 | 0.000 |
| dev-50 | false_premise | direct | answered | fully_correct | 0.000 |
| dev-50 | false_premise | direct | answered | citation_valid_answer | 0.000 |
| dev-51 | downstream | all | answered | columns_f1 | 0.000 |
| dev-51 | downstream | all | answered | models_f1 | 0.800 |
| dev-51 | downstream | all | answered | headline_f1 | 0.000 |
| dev-51 | downstream | all | answered | fully_correct | 0.000 |
| dev-51 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-52 | downstream | all | answered | columns_f1 | 0.148 |
| dev-52 | downstream | all | answered | models_f1 | 0.286 |
| dev-52 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-52 | downstream | all | answered | headline_f1 | 0.148 |
| dev-52 | downstream | all | answered | fully_correct | 0.000 |
| dev-52 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-53 | downstream | all | answered | columns_f1 | 0.110 |
| dev-53 | downstream | all | answered | models_f1 | 0.588 |
| dev-53 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-53 | downstream | all | answered | headline_f1 | 0.110 |
| dev-53 | downstream | all | answered | fully_correct | 0.000 |
| dev-53 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-54 | downstream | all | answered | columns_f1 | 0.286 |
| dev-54 | downstream | all | answered | models_f1 | 0.400 |
| dev-54 | downstream | all | answered | headline_f1 | 0.286 |
| dev-54 | downstream | all | answered | fully_correct | 0.000 |
| dev-54 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-55 | downstream | all | answered | columns_f1 | 0.000 |
| dev-55 | downstream | all | answered | models_f1 | 0.667 |
| dev-55 | downstream | all | answered | headline_f1 | 0.000 |
| dev-55 | downstream | all | answered | fully_correct | 0.000 |
| dev-55 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-56 | downstream | all | answered | columns_f1 | 0.400 |
| dev-56 | downstream | all | answered | models_f1 | 0.400 |
| dev-56 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-56 | downstream | all | answered | headline_f1 | 0.400 |
| dev-56 | downstream | all | answered | fully_correct | 0.000 |
| dev-57 | downstream | all | answered | columns_f1 | 0.000 |
| dev-57 | downstream | all | answered | models_f1 | 0.600 |
| dev-57 | downstream | all | answered | headline_f1 | 0.000 |
| dev-57 | downstream | all | answered | fully_correct | 0.000 |
| dev-57 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-58 | downstream | all | answered | columns_f1 | 0.400 |
| dev-58 | downstream | all | answered | models_f1 | 0.750 |
| dev-58 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-58 | downstream | all | answered | headline_f1 | 0.400 |
| dev-58 | downstream | all | answered | fully_correct | 0.000 |
| dev-58 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-59 | downstream | all | answered | columns_f1 | 0.800 |
| dev-59 | downstream | all | answered | models_f1 | 0.800 |
| dev-59 | downstream | all | answered | headline_f1 | 0.800 |
| dev-59 | downstream | all | answered | fully_correct | 0.000 |
| dev-60 | downstream | all | answered | columns_f1 | 0.000 |
| dev-60 | downstream | all | answered | models_f1 | 0.333 |
| dev-60 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-60 | downstream | all | answered | headline_f1 | 0.000 |
| dev-60 | downstream | all | answered | fully_correct | 0.000 |
| dev-60 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-61 | downstream | all | answered | columns_f1 | 0.000 |
| dev-61 | downstream | all | answered | models_f1 | 0.800 |
| dev-61 | downstream | all | answered | headline_f1 | 0.000 |
| dev-61 | downstream | all | answered | fully_correct | 0.000 |
| dev-62 | downstream | all | answered | columns_f1 | 0.000 |
| dev-62 | downstream | all | answered | models_f1 | 0.000 |
| dev-62 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-62 | downstream | all | answered | headline_f1 | 0.000 |
| dev-62 | downstream | all | answered | fully_correct | 0.000 |
| dev-62 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-63 | downstream | all | answered | columns_f1 | 0.143 |
| dev-63 | downstream | all | answered | models_f1 | 0.667 |
| dev-63 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-63 | downstream | all | answered | headline_f1 | 0.143 |
| dev-63 | downstream | all | answered | fully_correct | 0.000 |
| dev-63 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-64 | downstream | all | answered | columns_f1 | 0.143 |
| dev-64 | downstream | all | answered | models_f1 | 0.400 |
| dev-64 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-64 | downstream | all | answered | headline_f1 | 0.000 |
| dev-64 | downstream | all | answered | fully_correct | 0.000 |
| dev-64 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-65 | downstream | all | answered | columns_f1 | 0.211 |
| dev-65 | downstream | all | answered | models_f1 | 0.444 |
| dev-65 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-65 | downstream | all | answered | headline_f1 | 0.211 |
| dev-65 | downstream | all | answered | fully_correct | 0.000 |
| dev-66 | downstream | all | answered | columns_f1 | 0.000 |
| dev-66 | downstream | all | answered | models_f1 | 0.267 |
| dev-66 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-66 | downstream | all | answered | headline_f1 | 0.000 |
| dev-66 | downstream | all | answered | fully_correct | 0.000 |
| dev-66 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-67 | downstream | all | answered | columns_f1 | 0.116 |
| dev-67 | downstream | all | answered | models_f1 | 0.250 |
| dev-67 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-67 | downstream | all | answered | headline_f1 | 0.116 |
| dev-67 | downstream | all | answered | fully_correct | 0.000 |
| dev-67 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-68 | downstream | all | answered | columns_f1 | 0.000 |
| dev-68 | downstream | all | answered | models_f1 | 0.267 |
| dev-68 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-68 | downstream | all | answered | headline_f1 | 0.000 |
| dev-68 | downstream | all | answered | fully_correct | 0.000 |
| dev-68 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-69 | downstream | all | answered | columns_f1 | 0.074 |
| dev-69 | downstream | all | answered | models_f1 | 0.182 |
| dev-69 | downstream | all | answered | exposures_f1 | 0.000 |
| dev-69 | downstream | all | answered | headline_f1 | 0.074 |
| dev-69 | downstream | all | answered | fully_correct | 0.000 |
| dev-69 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-70 | downstream | all | answered | columns_f1 | 0.462 |
| dev-70 | downstream | all | answered | models_f1 | 0.800 |
| dev-70 | downstream | all | answered | headline_f1 | 0.462 |
| dev-70 | downstream | all | answered | fully_correct | 0.000 |
| dev-70 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-71 | downstream | all | answered | columns_f1 | 0.000 |
| dev-71 | downstream | all | answered | models_f1 | 0.000 |
| dev-71 | downstream | all | answered | headline_f1 | 0.000 |
| dev-71 | downstream | all | answered | fully_correct | 0.000 |
| dev-71 | downstream | all | answered | citation_valid_answer | 0.000 |
| dev-72 | yesno | all | answered | yesno_correct | 0.000 |
| dev-72 | yesno | all | answered | fully_correct | 0.000 |
| dev-72 | yesno | all | answered | citation_valid_answer | 0.000 |
| dev-73 | yesno | all | answered | yesno_correct | 0.000 |
| dev-73 | yesno | all | answered | fully_correct | 0.000 |
| dev-75 | yesno | all | answered | yesno_correct | 0.000 |
| dev-75 | yesno | all | answered | fully_correct | 0.000 |
| dev-76 | yesno | all | answered | citation_valid_answer | 0.000 |
| dev-77 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-78 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-79 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-80 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-82 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-83 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-84 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-85 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-86 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-87 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-88 | meaning | None | answered | citation_valid_answer | 0.000 |
| dev-89 | dotted_near_miss | None | answered | refusal_correct | 0.000 |
| dev-89 | dotted_near_miss | None | answered | fully_correct | 0.000 |
| dev-89 | dotted_near_miss | None | answered | citation_valid_answer | 0.000 |
| dev-91 | dotted_near_miss | None | answered | refusal_correct | 0.000 |
| dev-91 | dotted_near_miss | None | answered | fully_correct | 0.000 |
| dev-91 | dotted_near_miss | None | answered | citation_valid_answer | 0.000 |
| dev-92 | dotted_typo | None | answered | refusal_correct | 0.000 |
| dev-92 | dotted_typo | None | answered | fully_correct | 0.000 |
| dev-92 | dotted_typo | None | answered | citation_valid_answer | 0.000 |
| dev-93 | unknown_model | None | answered | refusal_correct | 0.000 |
| dev-93 | unknown_model | None | answered | fully_correct | 0.000 |
