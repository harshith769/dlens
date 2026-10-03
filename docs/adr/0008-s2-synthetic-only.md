# 0008. S2 long-context runs on the synthetic corpus only

- Status: Accepted
- Date: 2026-10-03
- Source: docs/DLENS_SPEC.md, Section 0, row 8

## Context

Free-tier per-minute token caps are far below 1M tokens.

## Decision

Run S2 on the synthetic corpus only. On the public corpus, run it only if the prompt fits; otherwise report that it does not fit.

## Consequences

To be expanded in week 2 (spec Section 14).
