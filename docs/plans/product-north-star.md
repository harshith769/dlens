# DLens product north star

**Version:** v1, 4 Oct 2026. A direction document, not a commitment: it decides what v0.3 must not block, and what comes after v1.0.

---

## 1. The product in one sentence

**DLens is a local-first, verified lineage assistant for dbt: ask where a column comes from or what breaks if you change it, and get an answer where every claim is checked against your code.**

The benchmark (v1.0) proves the method works. The product makes it usable on a real team's project.

## 2. Who it is for, and the job it does

| User | Moment | What they need from DLens |
|---|---|---|
| Analytics engineer | Before renaming, dropping or changing a column | Every downstream column, model and dashboard affected, including join/filter-only dependencies |
| Data analyst | "Can I trust this number?" | The full path from source to this column, with the SQL lines that compute it |
| New joiner | First weeks on an unfamiliar dbt project | Plain-English answers that never invent tables or columns |
| Reviewer on a PR | Reviewing a model change | An automatic "blast radius" comment on the PR |

## 3. What makes DLens different (keep these true)

1. **Verified, not just generated.** The validator removes any claim the tools didn't return, visibly. Competitors either have no LLM layer (colibri, Canva extractor) or don't verify answers.
2. **Works on dbt Core, any warehouse, from artifacts.** No dbt Cloud, no Fusion, no warehouse credentials. As of Oct 2026 the official dbt MCP server's column lineage needs Fusion or the dbt platform (re-check before claiming this publicly).
3. **Local-first and private.** Trace, impact and explore need no LLM at all. Ask runs on a local model by default; cloud models only when the user configures their own key.
4. **Indirect edges.** Join keys and filters that never appear in a SELECT still show up in impact.
5. **Measured.** A public benchmark says how accurate it is, including where it loses.

## 4. Product surfaces (in build order)

| Surface | Release | What it is | LLM needed? |
|---|---|---|---|
| CLI | shipped (v0.1) | `dlens ingest / trace / impact / ask` | Only for `ask` |
| Artifact ingest, any dialect | v0.3 | `dlens ingest --artifacts target/`; tested in v0.3 on DuckDB, Snowflake, BigQuery, Postgres; other sqlglot dialects (Databricks, Redshift…) work but are untested until a user confirms | No |
| Local UI on your project | v0.3 | `dlens ui --project .`: Ask, Explore, Source, How it works | Only for Ask |
| Public demo | shipped (v0.2) | Streamlit Cloud on the synthetic corpus | Gemini, capped |
| MCP server | v1.1 | Tools (`resolve_entity`, `trace_upstream`, `impact_downstream`, `get_model_sql`, `search_docs`) plus **`verify_answer`**, so any AI assistant can check its own lineage claims against the graph | The user's assistant |
| PR impact bot | v1.2 | GitHub Action: build graphs for base and head, diff them, comment the blast radius | No |
| Scale + Diff | v1.3+ | 1,000+ models, incremental ingest; "why do these two numbers differ?" | Optional |

**Why MCP is the highest-leverage next surface:** users already work inside Claude Code, Cursor or similar. DLens doesn't need to pay for or host an LLM there; it provides the deterministic tools and the verifier. `verify_answer` is unique: no other tool lets an assistant check its lineage claims against code.

## 5. "Real-user ready" definition of done (target: v1.1)

A real user is served when all of these hold:
1. `pipx install "dlens-lineage[ui]"`, then `dlens ingest --artifacts target/`, then `dlens ui --project .` works in **under 5 minutes** on macOS, Windows or Linux, without sending code anywhere.
2. Parse coverage is **≥ 90% FULL** on their project, or `dlens report` explains exactly what failed and why.
3. Trace, impact and explore work with **no LLM**.
4. Ask works with a local model or the user's own key; **every answer is validated**, and removed claims are shown.
5. The same tools work inside their AI assistant via **MCP**.
6. Docs: a quickstart, a privacy statement, troubleshooting, and a known-limitations page.

## 6. Product success signals (no telemetry; privacy first)

- Design partners (2–3 from the owner's network) complete the quickstart on their own project.
- Parse coverage on 3–5 public projects, published in `docs/real-world-coverage.md`.
- GitHub issues filed by people other than the owner; PyPI downloads as a weak signal.
- Time from install to first trace, measured by the owner on a fresh machine.

## 7. What DLens will not do (still true after v1.0)

- No hosted SaaS that receives customer code; no telemetry.
- No training or fine-tuning; no LLM-extracted graphs.
- No non-dbt lineage (Airflow, Spark, notebooks).
- No paid tiers, no warehouse connections, no React rewrite before real users ask for it.

## 8. Open questions to revisit after v1.0

- Is Streamlit enough for the local UI, or does a static HTML export (shareable lineage page) serve teams better?
- Should `verify_answer` accept free text from any LLM (claim extraction) or only DLens's structured claims?
- dbt Cloud users without local artifacts: fetch artifacts through the dbt Cloud API?
