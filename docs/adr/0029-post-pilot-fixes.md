# 0029. Post-pilot fixes (S13b)

- Status: Accepted (owner, 22 Oct 2026; S13b STOP 1). Spec §0 row 37.
- Date: 2026-10-22
- Amends: the S4 agent after the S13 pilot freeze (no public interface changes; spec §7 stable)
- Implemented in: S13b, commits 59d22b3 (F5), 9cdb11b (F4), 03c8837 (F3), bac08bd (F2)
- Evidence: docs/plans/post-pilot-fixes.md (design, before-looking rules, decisions);
  eval/reports/s13b/diagnosis.md (step 0, read-only); eval/reports/s13/prep_audit.md;
  docs/plans/pilot-design.md §3.1, §4, §5

## Context

The S13 dev pilot (pilot table at 1c59483, agent-code sha `a6fb5b2e…b424`) found four validator
or loop behaviours that dropped correct dev content or caused false refusals (F1–F4), one
transport-error crash in the Gemini adapter (F5) and a group of qwen Ask refusals (F6). The S4
pilot freeze held them until the table was committed. Every fix changes `src/dlens/agent`, and
so the agent-code sha.

## Rules stated before looking (owner, recorded verbatim in post-pilot-fixes.md)

- F1 hop bound: if the diagnosis shows option (a) applies, the new MAX_COMPLETION_HOPS = the
  longest shortest-bridge among the gold-consistent dropped claims, and it may not exceed 6. If
  any needed bridge is longer than 6, option (a) alone is reported as insufficient, with no
  larger bound.
- F4 prefix: MIN_PREFIX_HEX = 5 as written in the design; the uniqueness check stays; no other
  value is tried.
- F6 threshold: no minimum hit-score threshold is added in S13b unless the diagnosis shows an
  unanswerable dev question that would get a docs-based answer. If so, STOP; a threshold rule is
  then proposed in writing before any value is computed.

The step 0 diagnosis rebuilt every question's ledger from the committed records and re-ran the
unchanged validator: qwen 77 / 77 and Gemini 88 / 88 validated records reproduced exactly.

## Decision

Approved and implemented:
- **F5 (a):** the Gemini adapter maps `httpx.TransportError` to `ProviderError(retryable=True,
  status_code=None)`. The loop retries once; a second failure is one failed record, and the
  runner continues. **A4 sub-item:** `APIError` and transport errors are raised after the
  `except` block with `from None`, so neither `__cause__` nor `__context__` keeps the SDK or
  httpx error (whose request holds the key).
- **F4 (a):** R2r repairs a unique same-prefix id prefix of ≥ 5 hex characters (was 7).
- **F3 (a):** a refused regenerate after a non-refused first draft goes to salvage instead of
  being returned as a pass. Salvage is unchanged; a code verdict still needs an R9 failure on an
  `r_` fact.
- **F2 (a):** in R4, `alias.column` is "not a node name" when `alias` is a ref / source alias, a
  CTE or a derived-table name in the source file of a model in the question's evidence
  (a regex, as metrics M7 (iv-k+), extended to Jinja ref/source aliases). An alias that is also
  a model name is checked as the model.

Deferred:
- **F1:** the gold-consistent R8 drops are joined only through indirect (JOIN/FILTER) edges,
  which no designed option reaches ((a) bound 5 recovers 1 of 55, (b) 0, (c) 1). Option (d)
  (indirect bridges under the family's traversal allowlist) is recorded as design only, for a
  later session.
- **F6:** the threshold STOP applied: qwen dev-93–96 (unanswerable) would reach the code
  search_docs step, which always returns hits. A gate-first design (known-node / doc-term check
  before any threshold) is recorded for a later session.

## Agent-code sha

`s4.agent_code_sha256()` after S13b: `77e25642205637bb458f3dc66703ffa75a57d68b4a1861bd08aa9e3b20ceb6d7`.
The committed pilot records keep `a6fb5b2e49fe9a104c3828c402d186196601c50c4ea25dadef0dbc982952b424`
and are not rewritten; `tests/unit/eval/test_s4.py` pins both separately (owner amendment A2).
`scripts/check_s4_repro.py` compares two record files and never reads the sha, so it needed no
change.

## The honest check

Every fix comes from dev cases, and the dev cases are unit tests that pin the mechanism, not a
score. One labelled diagnostic dev re-run is reported for information only and does not replace
the pilot table. **The honest check is the test set, after the 7 Dec 2026 freeze**, with these
fixes frozen as part of the S4 system.

## Consequences

- S4 dev numbers from before S13b (the pilot table) and after are from different agent code; no
  report mixes them.
- S1 is untouched: `s1.frozen_hashes()` is unchanged. F5 changes the Gemini adapter S1 also
  uses, which the B8 hashes do not cover; the S1 design change log records it.
- Recorded, not changed: `openai_compat.py` raises `from None` inside its `except` block, so its
  `__context__` still holds the httpx error and its request; `ollama.py` maps a connection error
  as non-retryable.
