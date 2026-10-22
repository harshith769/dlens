## Run notes (hand-written; every number from committed records, manifests or the quota counter)

**LLM calls per question (S4):** qwen 3.32 (319 calls, 0 cached), Gemini 4.51 (433 calls in the
final records). S1 makes 1 call per question on both models.

**Gemini quota (budget 475 / Pacific day, pilot-design §3):** 530 counted calls over two Pacific
days. On 21 Oct, 475: S1 used 96, and S4 used 379, including the call lost in the dev-38 crash.
On 22 Oct, S4 used 55. S4 total: 434 counted, 433 in the records. The local counter shows
`gemini 2026-10-21: 475` and `gemini 2026-10-22: 55`. The counter only sees this machine; the
owner confirmed nothing else uses the project.

**S4 Gemini run history (pilot-design §3.1):**
- dev-38: the first pass crashed with `httpx.RemoteProtocolError` (a transport error that the
  Gemini adapter does not map to a retryable `ProviderError`; post-pilot fix **F5**). The resume
  replayed every successful call from the cache, so dev-38 is split across passes.
- dev-82: `QuotaExceeded` on 21 Oct. It was finished on 22 Oct (2 calls cached, 2 fresh), so it
  is also split across days.
- Not fixed in the pilot: the freeze holds, and the resume from the cache was free.

**Code refusals (no LLM call):** dev-19 and dev-89–92, refused by code as unknown columns, on
both models. They are scored like any record.

**Gemini S4 latency (small n):**
- The response cache stores responses, not their latency, so replayed calls carry no provider
  latency.
- The all-fresh column covers the **10** questions whose calls were all fresh in one pass
  (dev-83–88, dev-93–96): p50 **7.6 s** (nearest rank, M15), range 5.7–47.6 s. The interpolated
  median of the same 10 is 8.3 s (the figure quoted on 22 Oct).
- The three at 46–48 s include waits on the client's 15-RPM rate limiter.
- metrics.py's own row (n = 15) also counts the 5 code refusals, whose latency is milliseconds.
- None of these latencies is comparable with qwen's (local GPU, n = 91 all-fresh).

**"No verifiable claims" (refused by the validator):** qwen dev-43, dev-46; Gemini dev-75, dev-87.

## S12b answer-quality observations: status after the pilot

| # | S12b observation (qwen) | qwen pilot | Gemini pilot | status |
|---|---|---|---|---|
| 1 | Validation lowers node-set F1 and raises false refusals | 0.597 → 0.561; false refusal 0.115 → 0.149 | 0.644 → 0.598; false refusal 0.000 → 0.023 | **Holds on both models.** Prep audit: R8 and R4 drops (F1, F2), dev-75 regenerate (F3) |
| 2 | dev-46 ends refused by the validator | refused ("no verifiable claims") | answered | **qwen only.** Cause: R4 on a SQL alias (F2) |
| 3 | Chain raw 1.0 → validated 0.5 | dev-16 (truncated id, F4) | 1.0 → 1.0 (n = 2) | **qwen only** |
| 4 | Augmentation raises impact F1 | 0.524 → 0.707 | 0.532 → 0.887 | **Holds, larger on Gemini.** Trace F1 does not move on either |
| 5 | search_docs rarely used | 8 questions, 7 answers cite chunks | 22 questions, 11 answers cite chunks | **Used more on Gemini.** Ask is now scored (AI-scored, see the Ask section), but S4 is below S1 on Ask on both models, and Ask does not isolate what the chunks add |
| 6 | Spurious `uncovered_parts` | 4 / 68 (validated) | 2 / 80 (validated) | **Holds on both** (unscored) |
| 7 | Premise rejection 0.5, no `premise_corrected` flag | 0.5 (prose 2, neither 2) | 0.75 (field 1, both 2, neither 1) | **Gemini uses the flag;** one spurious flag on each model |

## Draft resume line (draft, owner approves)

> *Draft, owner approves; dev pilot numbers, not a test-set result:* Built DLens, an open-source
> dbt column-lineage tool whose LLM agent answers with citations checked by a code validator. On
> a 96-question dev pilot, it beat a vector-RAG baseline on node-set F1 by +0.32 on local
> qwen3:4b (0.24 → 0.56) and by +0.21 on Gemini 3.5 Flash-Lite (0.39 → 0.60). Both gains have
> 95% paired-bootstrap CIs above zero, and validated answers contained no hallucinated
> identifiers on either model.
