# Explain: LLM access layer (`src/dlens/agent/llm/`)

## What it does
`LLMClient.chat(messages, tools=None) -> LLMResponse(text, tool_calls, usage, cached)` is the only
way DLens talks to a model. `make_client()` picks the provider from `DLENS_PROVIDER` (default
`ollama`; also `gemini`, `openai` and `groq`, the last two through one OpenAI-compatible adapter). Around every call the client
enforces, in this order:

1. **Token cap**: estimate input tokens, raise `InputTooLarge` above 3,000.
2. **Cache**: a hit returns immediately (`cached=True`) with no limiter, no quota, no network.
3. **Quota**: `QuotaExceeded` is raised *before* anything is sent.
4. **Rate limiter**: may sleep so the provider's requests-per-minute is respected.
5. **Provider send**, then store the response in the cache.

**Structured output.** `chat(..., response_schema=<JSON schema dict>)` asks the provider for JSON
that matches the schema, returned in `LLMResponse.text` (the agent's answer phase parses it with
Pydantic). Ollama gets `format=<schema>` (compiled to a grammar); Gemini gets
`response_mime_type="application/json"` and `response_json_schema=<schema>` (`response_schema`
wants the SDK's `Schema` type or a Pydantic class, not a plain dict). The schema counts toward the
token estimate and is part of the cache key, but only when set, so entries cached before the
option existed still hit.

## How each part works
- **`types.py`**: Pydantic models (`Message`, `ToolSpec`, `ToolCall`, `Usage`, `LLMResponse`) that
  round-trip through JSON, because the cache stores them. `ToolCall.provider_meta` holds opaque
  provider strings that must be replayed with the history.
- **`tokens.py`**: `ceil(len(json) / 3)`. JSON and SQL run at 3-4 characters per token, so this
  slightly over-counts and never lets an oversize call through.
- **`cache.py`**: SQLite. Key = `sha256` of canonical JSON (sorted keys) of provider, model,
  messages, tools, `params` and (when set) `response_schema`. `params` is whatever else changes
  the output (temperature, thinking level, `num_ctx`). Only successful responses are stored.
- **`quota.py`**: SQLite table `(provider, day, count)`. The "day" is the date in
  `America/Los_Angeles`, so the count resets at Pacific midnight, DST-safe (`zoneinfo`).
  `reserve()` checks and increments in one `BEGIN IMMEDIATE` transaction, so two processes cannot
  both take the last slot. Gemini budget = `GEMINI_DAILY_BUDGET` (default 400). `used()` and
  `remaining()` are public so the eval runner can apply the spec 11.6 95% early-stop; the client
  itself blocks at the full budget.
- **`ratelimit.py`**: a 60 s sliding window of send times; when full, sleep until the oldest slot
  expires. Gemini 15, Groq 30, Ollama unlimited. Clock and sleep are injectable.
- **`ollama.py`**: `qwen3:4b-instruct-2507-q4_K_M`, `temperature 0`, `num_ctx 8192`, `think=False`. Tool-call ids are
  `call_{index}`, never random, so a replayed history hashes to the same cache key.
- **`gemini.py`**: `google-genai` with automatic function calling disabled (we run our own loop).
  Key from `GEMINI_API_KEY` in the process environment only; `.env` is never opened. The model ID
  comes from `DLENS_GEMINI_MODEL` and `-latest` aliases are rejected.
- **`openai_compat.py`** (S11, ADR 0012): one adapter for any OpenAI-compatible
  `/chat/completions` endpoint (Groq, OpenRouter, LM Studio, vLLM, OpenAI, Ollama's own `/v1`),
  written on plain `httpx`. `DLENS_PROVIDER=openai` reads `DLENS_OPENAI_BASE_URL`,
  `DLENS_OPENAI_MODEL` and `DLENS_OPENAI_KEY_ENV` (the *name* of the variable holding the key), plus
  `DLENS_OPENAI_TEMPERATURE` (default 0), `DLENS_OPENAI_JSON_MODE`, `DLENS_OPENAI_DAILY_BUDGET`
  (calls/day) and `DLENS_OPENAI_RPM`. **Groq is a preset**: `DLENS_PROVIDER=groq` is this
  adapter with Groq's base URL, key variable `GROQ_API_KEY`, model `DLENS_GROQ_MODEL`, budget
  `GROQ_DAILY_BUDGET` and 30 RPM. Messages map to the OpenAI shape: assistant `tool_calls` with
  JSON-string arguments, `tool` messages with `tool_call_id`. A `response_schema` becomes
  `response_format: json_schema` (or `json_object`, or nothing, via the JSON mode, for endpoints
  that lack schema support). Returned tool-call ids are renumbered `call_{i}`, as in Ollama, and
  `<think>` blocks are stripped. `params` = base URL, temperature and JSON mode, so **the same
  model id on two endpoints never shares a cache entry**, with no change to `cache.py`.
  - **The key.** Only the variable's name is kept. The value is read at send time for the
    `Authorization` header and nowhere else: not in `params` (the cache key), the cache, the quota
    file, run records, manifests or exception text. Errors are built from the status and at most
    300 characters of the response body and raised `from None`, because a chained httpx exception
    holds the request and the request holds the header. A test sets the key to a sentinel string
    and searches every written file and raised message for it. Never put a key in the base URL.
  - **Cloud guard.** A base URL whose host isn't `localhost`, `127.0.0.1` or `::1` needs a key and
    a daily call budget, or `make_client` refuses: a cloud call is never unmetered. Groq's
    documented tokens/day limit (`GROQ_DAILY_TOKENS`) is not enforced by the counter; the
    calls/day budget is the guard.
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
- **Local model is the Instruct-2507 build, not `qwen3:4b`.** The `qwen3:4b` tag is the
  thinking-only 2507 build: its chat template inserts `<think>` itself, so `think=False` cannot
  turn reasoning off. Observed live on Ollama 0.35: ~140 output tokens (reasoning followed by a bare
  `</think>`) for a one-word answer. `qwen3:4b-instruct-2507-q4_K_M` is the non-thinking build at
  the same size, so no extra VRAM and the 3K-token input cap is unaffected. `strip_think` stays as a
  safety net: it handles closed blocks, unterminated blocks and a bare closing tag.

## Alternatives rejected
- **The Groq SDK** (the original plan): it locks the cross-check and judge to one free tier, and
  real users want their own provider. `groq` left the `agent` extra in S11 (ADR 0012).
- **The `openai` SDK for the compatible adapter**: another dependency for one POST. Plain `httpx`
  (already installed by `ollama` and `google-genai`) gives full control over headers and error text.
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
4. A teammate points `DLENS_OPENAI_BASE_URL` at a hosted endpoint and gets "needs a daily call
   budget". Why does the local endpoint not need one, and why is the base URL part of `params`
   while the API key is not?
5. An httpx call to the endpoint fails with a 401. Walk through what the user sees, and why the
   adapter raises `ProviderError(...) from None` instead of chaining the httpx exception.
6. Groq returns tool calls with ids like `call_abc123xyz`. What does the adapter do with them,
   and what would happen to the cache on a replayed tool-phase history if it kept them?
