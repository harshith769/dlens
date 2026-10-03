# Explain: LLM access layer (`src/dlens/agent/llm/`)

## What it does
`LLMClient.chat(messages, tools=None) -> LLMResponse(text, tool_calls, usage, cached)` is the only
way DLens talks to a model. `make_client()` picks the provider from `DLENS_PROVIDER` (default
`ollama`; `gemini` also works; `groq` is a clear "not yet" error). Around every call the client
enforces, in this order:

1. **Token cap**: estimate input tokens, raise `InputTooLarge` above 3,000.
2. **Cache**: a hit returns immediately (`cached=True`) with no limiter, no quota, no network.
3. **Quota**: `QuotaExceeded` is raised *before* anything is sent.
4. **Rate limiter**: may sleep so the provider's requests-per-minute is respected.
5. **Provider send**, then store the response in the cache.

## How each part works
- **`types.py`**: Pydantic models (`Message`, `ToolSpec`, `ToolCall`, `Usage`, `LLMResponse`) that
  round-trip through JSON, because the cache stores them. `ToolCall.provider_meta` holds opaque
  provider strings that must be replayed with the history.
- **`tokens.py`**: `ceil(len(json) / 3)`. JSON and SQL run at 3-4 characters per token, so this
  slightly over-counts and never lets an oversize call through.
- **`cache.py`**: SQLite. Key = `sha256` of canonical JSON (sorted keys) of provider, model,
  messages, tools and `params`. `params` is whatever else changes the output (temperature, thinking
  level, `num_ctx`). Only successful responses are stored.
- **`quota.py`**: SQLite table `(provider, day, count)`. The "day" is the date in
  `America/Los_Angeles`, so the count resets at Pacific midnight, DST-safe (`zoneinfo`).
  `reserve()` checks and increments in one `BEGIN IMMEDIATE` transaction, so two processes cannot
  both take the last slot. Gemini budget = `GEMINI_DAILY_BUDGET` (default 400). `used()` and
  `remaining()` are public so the eval runner can apply the spec 11.6 95% early-stop; the client
  itself blocks at the full budget.
- **`ratelimit.py`**: a 60 s sliding window of send times; when full, sleep until the oldest slot
  expires. Gemini 15, Groq 30, Ollama unlimited. Clock and sleep are injectable.
- **`ollama.py`**: `qwen3:4b`, `temperature 0`, `num_ctx 8192`, `think=False`. Tool-call ids are
  `call_{index}`, never random, so a replayed history hashes to the same cache key.
- **`gemini.py`**: `google-genai` with automatic function calling disabled (we run our own loop).
  Key from `GEMINI_API_KEY` in the process environment only; `.env` is never opened. The model ID
  comes from `DLENS_GEMINI_MODEL` and `-latest` aliases are rejected.
- **`config.py`**: cache at `$XDG_CACHE_HOME/dlens/llm.sqlite` (override `DLENS_CACHE_DIR`), quota
  at `$XDG_STATE_HOME/dlens/quota.sqlite` (override `DLENS_STATE_DIR`).

## Why this design
- **One door.** Quota, cache and cap can't be bypassed if nothing else imports a provider SDK.
- **Cache before quota.** Re-running an interrupted benchmark costs nothing (spec 11.6: runs are
  resumable from the cache).
- **Quota is a separate file from the cache**, so deleting the cache can never give back budget.
- **Quota counts at send time, including calls that fail**: Google counts those against RPD too.
  Cache hits and refused calls never count.
- **Gemini temperature is not forced to 0.** Google recommends the default 1.0 for Gemini 3, and
  lower values can degrade it. `DLENS_GEMINI_TEMPERATURE` (default 1.0) and `DLENS_GEMINI_THINKING`
  (unset = model default) are configurable and part of the cache key. Reproducibility comes from the
  cache, not from sampling. Ollama stays at temperature 0.
- **Thought signatures.** Gemini 3 returns a `thought_signature` on function-call parts and
  rejects the next request (HTTP 400) if the history omits it. The adapter stores it base64 in
  `ToolCall.provider_meta` and replays it. It survives the cache because it is plain JSON.
- **No automatic retries.** `ProviderError` carries `status_code` and `retryable`; the agent loop
  decides, since a retry spends quota and wall time.
- **qwen3 leaks reasoning even with `think=False`** (observed live on qwen3:4b with Ollama 0.35): the
  reasoning arrives in `content` followed by a bare `</think>`, with no opening tag. `strip_think`
  handles closed blocks, unterminated blocks and this "closing tag only" form.

## Alternatives rejected
- **LiteLLM / LangChain wrappers**: a big dependency and they hide the thought-signature and quota
  details this layer exists to control (spec: no agent framework).
- **A real tokenizer** (tiktoken, model tokenizers): none matches both Gemini and Qwen, and
  needing network or weights to count tokens is worse than a safe over-estimate.
- **Counting only successful calls**: undercounts versus Google's counter, so the budget would lie.
- **Resetting at UTC midnight or a rolling 24 h**: not when Google resets RPD.
- **In-memory counter or a quota column in the cache DB**: lost on restart, or erasable with the cache.

## Explain-back questions
1. A cache hit happens when the quota is exhausted. What does the client return and why is that
   safe? What would break if the quota check ran *before* the cache lookup?
2. Why does `reserve()` use one `BEGIN IMMEDIATE` transaction instead of `used()` followed by
   `record()`? Describe the overshoot that two parallel eval runs could cause otherwise.
3. You change `DLENS_GEMINI_TEMPERATURE` from 1.0 to 0.5. What happens to old cache entries, and
   why is that the right behaviour? What goes wrong if a tool call's `thought_signature` is dropped
   when history is replayed?
