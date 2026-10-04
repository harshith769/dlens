# 0012. OpenAI-compatible adapter replaces the Groq-specific SDK

- Status: Accepted
- Date: 2026-10-04
- Source: docs/DLENS_SPEC.md, Section 0, row 22
- Implemented in: S11 (D1)

## Context

The Groq adapter was never built. Real users want their own provider, and Groq's free tier may change before the v1.0 judge calibration.

## Decision

One OpenAI-compatible adapter behind `LLMClient` (base URL, key and model from env). Groq becomes one configuration of it. The cross-check and judge model is chosen before v1.0 judge calibration: Groq `openai/gpt-oss-120b` if still free, else another free OpenAI-compatible endpoint.

## Consequences

- One adapter covers Groq, OpenRouter, LM Studio, vLLM and OpenAI.
- The `groq` dependency leaves the `agent` extra when D1 lands; until then pyproject still lists it.
- Cache, quota and token cap stay in `LLMClient`, unchanged.

## Alternatives rejected

- Groq SDK only: locks users and the judge to one free tier.
- LiteLLM: a large dependency for what is one HTTP shape.
