# 0002. Local Qwen model as second full-run model; Groq demoted

- Status: Accepted
- Refined by 0011 (exact build: qwen3:4b-instruct-2507-q4_K_M)
- Date: 2026-10-03
- Source: docs/DLENS_SPEC.md, Section 0, row 2

## Context

A local Qwen3 model on the RTX 4050 (6 GB) has unlimited quota. Groq's free tier is limited to 200K tokens/day on gpt-oss-120b.

## Decision

Use a local Qwen3 model via Ollama as the second full-run model. Groq is a small cross-check and the LLM judge. (Spec v1.3 later set qwen3:4b, since 8B spills to CPU.)

## Consequences

To be expanded in week 2 (spec Section 14).
