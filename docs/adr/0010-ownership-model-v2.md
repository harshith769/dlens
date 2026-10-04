# 0010. Ownership model v2 and the explain gate

- Status: Accepted (supersedes 0009)
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, row 21
- Implemented in: this session (S00)

## Context

Spec v1.1 had the owner hand-write the lineage engine, validator rules, linker scorer and metrics. In practice Claude Code built v0.1 and v0.2 in about two days, with the owner reviewing. ADR 0009 recorded "AI writes all code" but did not say how understanding is enforced.

## Decision

Claude Code writes all code. The owner owns design (approves every plan, ADR and design doc), gold data (corpus design, model review, question review, freezes) and acceptance (each plan and tag). Before every tag the owner passes an explain gate: answering the explain-back questions in each changed `docs/explain/*.md` without notes. `src/dlens/lineage/`, `eval/metrics.py`, the linker scorer and the validator rules are owner-gated: they change only when an approved plan names them.

## Consequences

- Speed matches how the project is actually built; honest interview phrasing is in spec Section 19 (from v0.3-plan Section 6).
- Every core change costs an explain doc update; a module the owner cannot explain is rewritten or re-explained before release.
- Gold independence now rests on process (design-first gold, oracle, C1), not on who typed the code.

## Alternatives rejected

- Keep hand-written zones: did not match reality and would slow every release.
- No gate at all: the owner could ship code they cannot defend.
