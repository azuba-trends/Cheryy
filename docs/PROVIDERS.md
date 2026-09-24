# CHERYY Provider model

The runtime AI is provided through capability-based routing against
discovered models.

## Capabilities

CHERYY recognises these capabilities:

| Capability | Used for |
| --- | --- |
| `general_reasoning` | Default chat |
| `agent_planning` | Planning a multi-step task |
| `multimodal_vision` | Reading screenshots / documents |
| `live_voice` | Gemini Live (bidi WebSocket) |
| `text_to_speech` | TTS fallback when Live is unavailable |
| `transcription` | STT fallback |
| `structured_tool_calling` | Tool-using chat |
| `embedding` | Memory retrieval |
| `image_generation` | Optional, disabled by default |

## Provider list

* **Google Gemini** (primary)
* **Ollama** (local, optional, autodetected)

Both providers expose the same capability vocabulary. CHERYY picks the
best model per capability, preferring free-tier Gemini Flash models.

## Free-first defaults

* `general_reasoning`     → `gemini-1.5-flash` (or latest Flash)
* `agent_planning`        → `gemini-1.5-pro` (or latest Pro)
* `multimodal_vision`     → `gemini-1.5-flash`
* `live_voice`            → `gemini-2.0-flash-exp`
* `text_to_speech`        → `gemini-2.5-flash-preview-tts`
* `embedding`             → `text-embedding-004`

If your quota is exhausted for one model, the registry falls back to
another accessible model with the same capability — and, if that fails,
to Ollama.

## Quota & rate-limit handling

* Every successful request increments `quota_state.requests_today` and
  `tokens_today`.
* `RateLimitedError` triggers exponential backoff (default 30 s).
* `QuotaExceededError` triggers fallback to Ollama.
* The UI shows current quota state in **Settings → AI Status**.
* Nothing is silently swallowed — the UI always shows the actual result.

## Adding another provider

1. Implement the relevant `cheryy.providers.base.*Provider` interface(s).
2. Map model ids to capabilities via
   `infer_capabilities(...)` (extend if you support a new naming convention).
3. Register in `cheryy.providers.registry.ProviderRegistry.initialize()`.
4. Add unit tests in `backend/tests/test_providers.py`.

The agent code never talks to a specific provider — it always asks
`ProviderRegistry.generate(...)`. This is what keeps CHERYY vendor-neutral.
