# CHERYY Backend HTTP API

The desktop UI talks to the backend over `http://127.0.0.1:7480`. The same
endpoints are documented here so external scripts / CLIs can drive the
same agent.

Full Swagger UI is available at <http://127.0.0.1:7480/docs>.

## Setup

| Verb | Path | Body | Notes |
| --- | --- | --- | --- |
| POST | `/setup/validate_key` | `{api_key}` | Real `listModels` call |
| POST | `/setup/apply_key`    | `{api_key}` | Persists + reinitialises providers |
| GET  | `/setup/self_test`    | — | Capability report |
| GET  | `/setup/status`       | — | Providers + quota snapshot |

## Chat

| Verb | Path | |
| --- | --- | --- |
| GET  | `/chat/conversations` | list conversations |
| GET  | `/chat/conversations/{cid}/messages` | list messages |
| POST | `/chat/send`          | `{message, conversation_id?}` → `{reply, task_id?, spoken?}` |

## Tasks

| Verb | Path | |
| --- | --- | --- |
| GET  | `/tasks` | list |
| GET  | `/tasks/{id}` | one |
| POST | `/tasks/{id}/pause` | pause |
| POST | `/tasks/{id}/resume` | resume |
| POST | `/tasks/{id}/cancel` | cancel |

## Memory

| Verb | Path | Body |
| --- | --- | --- |
| GET  | `/memory?category=...` | — |
| POST | `/memory` | `{category, content, importance?, confidence?, tags?}` |
| POST | `/memory/search` | `{query, categories?, top_k?}` |
| DELETE | `/memory/{id}` | — |

## Filesystem

| Verb | Path | |
| --- | --- | --- |
| GET  | `/files?path=...&recursive=...` | list (safe roots only) |
| POST | `/files/action` | run a registered tool: `{name, args}` |

## Live PC

| Verb | Path | |
| --- | --- | --- |
| GET  | `/monitors` | multi-monitor layout |
| GET  | `/running_apps` | enumerate visible apps |
| GET  | `/activity` | last N log events |
| GET  | `/providers/status` | provider / quota snapshot |

## Diagnostics

| Verb | Path | |
| --- | --- | --- |
| GET  | `/diagnostics/health` | full health report |
| POST | `/diagnostics/repair` | safe repair (never deletes user data) |

## WebSocket

| Path | Direction | Purpose |
| --- | --- | --- |
| `/ws/events` | server → client | Live activity feed |
| `/ws/voice`  | duplex | Live / TTS+STT voice session |

### Voice protocol

The client sends:

```json
{"kind":"audio","pcm_b64":"<base64 16-bit LE PCM>"}
{"kind":"text", "text":"hello"}
{"kind":"stop"}
```

The server sends:

```json
{"type":"voice_state","state":"listening"|"speaking"|...}
{"type":"voice_transcript","role":"assistant","text":"..."}
```
