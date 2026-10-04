# 0011. Local benchmark model is qwen3:4b-instruct-2507-q4_K_M

- Status: Accepted (refines 0002)
- Date: 2026-10-03
- Source: docs/DLENS_SPEC.md, Section 0, row 19
- Implemented in: already in code (v0.2)

## Context

ADR 0002 made a local Qwen3 the second full-run model. Qwen3-8B spills to the CPU on the 6 GB RTX 4050. The `qwen3:4b` tag is the thinking-only build, and its reasoning leaked into answers.

## Decision

Use `qwen3:4b-instruct-2507-q4_K_M` (Qwen3-4B-Instruct-2507, non-thinking) via Ollama at `num_ctx` 8192 for development and the second benchmark run.

## Consequences

- 3.9 GB, 100% GPU, about 62 tok/s; unlimited free runs.
- A 4B model is weaker at multi-step tool calling; code-initiated steps and coverage completion carry correctness, and any weakness is reported.

## Alternatives rejected

- `qwen3:8b`: spills to CPU (~16 tok/s).
- `qwen3:4b` thinking build: leaks reasoning; needs prompt hacks to disable.
