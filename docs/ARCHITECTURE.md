# CHERYY Architecture

> _Your personal AI office assistant._

CHERYY is a local-first Windows desktop application composed of:

  * a **Python backend** (`backend/`) — providers, security, memory, tasks,
    tools, computer / browser / office automation, voice, publishing,
    scheduler, skill registry, diagnostics, FastAPI surface;
  * a **React + TypeScript desktop UI** (`desktop/`) — Vite, Zustand, designed
    to be packaged by **Tauri** into a Windows MSI / NSIS installer;
  * a **Tauri shell** (`desktop/src-tauri/`) — starts the backend sidecar
    on launch and stops it on exit.

The runtime AI is the **user's Gemini API key**, validated on first run. The
local Ollama install (when present) is an *optional* fallback. The MiniMax
model that built the codebase is not required at runtime.

## High-level pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│  Tauri window (React UI)                                         │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ Sidebar • Chat • Tasks • LivePC • Files • Memory • …      │   │
│  └───────────────────────────────────────────────────────────┘   │
│            │  HTTP (localhost:7480)   │  WS /ws/events            │
│            ▼                         │  WS /ws/voice             │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │ FastAPI surface  (cheryy.api)                              │  │
│  ├───────────────────────────────────────────────────────────┤  │
│  │ Agent (cheryy.agent) — chat, plan, execute, observe       │  │
│  │ Task engine (cheryy.tasks) — checkpoints, cancel, retry   │  │
│  │ Tools (cheryy.tools) — registry, gate, audit              │  │
│  │ Memory (cheryy.memory) — relevance retrieval             │  │
│  ├───────────────────────────────────────────────────────────┤  │
│  │ Providers (cheryy.providers) — Gemini + Ollama + dispatch │  │
│  │ Security (cheryy.security) — programmatic no-delete       │  │
│  │ Voice (cheryy.voice) — Live, TTS, STT, barge-in          │  │
│  │ Computer (cheryy.computer) / Browser (cheryy.browser)     │  │
│  │ Office (cheryy.office) / Image / Publishing              │  │
│  │ Scheduler / Skills / Diagnostics / Setup                 │  │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

## First-run flow

1. User launches CHERYY. UI shows **FirstRun** modal.
2. User pastes a Gemini API key → `POST /setup/validate_key`
   (real `listModels` call against `generativelanguage.googleapis.com`).
3. On success: `POST /setup/apply_key` stores the key in Windows
   Credential Manager (fallback: encrypted file) and runs `run_self_test`.
4. UI shows real capability flags and switches to the main app.

## The no-delete guarantee

The hard rule "never delete anything" is enforced in
`cheryy.security` not by prompts but by code:

  * `DestructiveActionInterceptor.assert_path_safe()` and
    `assert_shell_safe()` raise `PermissionError` for any verb matching
    `delete`, `unlink`, `rm`, `rmdir`, `shred`, `trash`, `Remove-Item`, `del`,
    `erase`, `format`, `diskpart`, etc.
  * `ActionPolicyEngine.decide()` DENIES any tool marked `destructive=true`
    regardless of granted permissions.
  * The fs toolset registers **no** delete / unlink / shred entry.
  * `fs.move` never overwrites and never deletes the source if the
    destination already exists — it copies instead and reports a note.

This is exercised by `tests/test_security.py` and `tests/test_filesystem.py`.

## Voice

Voice is the primary input mode but **chat replies are also spoken**:

  * `computer.get_active_window` is read first so we know which app to speak
    to (Windows + active Office apps work seamlessly).
  * Microphone PCM is VAD-prefiltered and streamed to Gemini Live when
    available; otherwise TTS+STT fallback.
  * Barge-in is implemented by `VoiceSession.push_audio` interrupting the
    playing `sd.play` stream.
  * `chat.send` always returns a `reply` which `agent.__call__` also pushes
    into `voice.speak(...)`. Chat and voice share the same transcript row
    in `messages`.

## Provider routing

`ProviderRegistry` owns:

  * `model_registry` (discovered models + capabilities)
  * `quota_state` (per-day requests/tokens/errors/quota_exhausted)
  * the per-capability default model (free-tier preferred)

`generate(...)` walks the provider list; on `QuotaExceededError` it falls
through to Ollama; on `RateLimitedError` it applies exponential backoff via
`base.with_retries`. Free-tier lookups prefer Flash models.

## Tools

Each tool returns `ToolResult` with:
  * `success`
  * `verification` (`True` only when observed reality matches expectation)
  * `observed_state`
  * `recovery` (ordered list of fallback strategies)
  * `latency_ms`

The agent never invents success — only verified tools can advance the
task.

## Storage

  * SQLite database at `<data_dir>/cheryy.db` (WAL mode)
  * Secrets in Windows Credential Manager (or `secrets.bin` fallback)
  * Logs under `<data_dir>/logs/cheryy.log` (rotated, 2 MB × 5)
  * Browser profile under `<data_dir>/browser_profile`
  * TTS / screenshot cache under `<data_dir>/cache/...`

`<data_dir>` defaults to `%LocalAppData%\CHERYY` and is overridable via
`CHERYY_DATA_DIR`.
