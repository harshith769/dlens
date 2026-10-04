# 0019. Two-track roadmap: research and product

- Status: Accepted
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, row 30
- Implemented in: this session (S00)

## Context

Build velocity is far above the hour-based plan. The binding limits are owner review time, Gemini quota days and Claude Code usage, not coding time.

## Decision

Run two tracks. Research: corpus v2 → indirect edges → retrieval → linker → questions → metrics → pilot → freeze → v1.0 benchmark. Product: artifact ingest → local UI on any project → v1.1 MCP server with `verify_answer` → v1.2 PR impact bot → v1.3+ scale and Diff. The product track never delays a research gate.

## Consequences

- Spare capacity becomes user-facing value; E1 also serves set E.
- If a week slips, C items drop first, then S items (G2, D1, E4b); M items never drop.

## Alternatives rejected

- Research only until v1.0: wastes capacity; no real users.
- Product first: risks the benchmark, the core contribution.
