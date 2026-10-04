# 0018. System freeze together with the test freeze

- Status: Accepted
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, row 29
- Implemented in: Freeze, Mon 7 Dec 2026 (v0.3-plan Section 5)

## Context

R2r, R8c and R9 were all added after the validator's first version. If the system keeps changing during test runs, test numbers mix systems.

## Decision

On 7 Dec 2026, with the test and set-E hashes, freeze the S4 system: prompts, validator version, model IDs and tool code are hashed into the run manifest. Any change after 7 Dec means re-running every system.

## Consequences

- Every test-set number comes from one known system.
- Fixes after the freeze are expensive by design.

## Alternatives rejected

- Freeze questions only: lets the system be tuned against test results indirectly.
- Freeze at v1.0 tag: too late; test runs start on 7 Dec.
