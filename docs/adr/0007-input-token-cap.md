# 0007. Hard per-call input-token cap of about 3K

- Status: Accepted
- Date: 2026-10-03
- Source: docs/DLENS_SPEC.md, Section 0, row 7

## Context

Free tiers have tokens-per-minute and tokens-per-day caps that bind before request caps.

## Decision

Enforce a cap of about 3K input tokens per call in code, inside LLMClient.

## Consequences

To be expanded in week 2 (spec Section 14).
