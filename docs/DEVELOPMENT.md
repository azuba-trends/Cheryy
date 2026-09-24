# Development guide

## Quick start (dev)

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv\Scripts\activate                  # Windows
# source .venv/bin/activate             # macOS / Linux
pip install -e .[dev]
cheryy-server                            # starts on http://127.0.0.1:7480

# 2. Desktop UI (in a second shell)
cd ..\desktop
npm install
npm run dev                              # vite dev server on :5173, proxies to backend
```

The proxy in `vite.config.ts` forwards `/api/*` and `/ws/*` to the FastAPI
server, so the dev UI talks to the real backend without CORS pain.

## Tests

```bash
cd backend
pytest                                   # runs security + provider + memory + fs + office + tasks
pytest tests/test_security.py -v         # security-focused run
pytest --cov=cheryy                      # coverage
```

The test suite uses **a separate data dir** per test (see `conftest.py`) so
the user's real CHERYY database is never touched.

## Adding a tool

```python
# in my_module.py
from cheryy.tools import tool

@tool(
    name="my.new_tool",
    description="What this does (used by the planner).",
    parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    category="fs",
)
async def my_new_tool(x: str) -> dict:
    return {"x": x}
```

That's it — the tool is now registered, gated by the security engine,
audited, and exposed to the planner. **Do not mark anything as
`destructive=True` unless you've added it to the forbidden set.**

## Adding a provider

1. Subclass `cheryy.providers.base.{LLMProvider, TTSProvider, ...}`.
2. Implement the relevant methods.
3. Register in `ProviderRegistry.initialize()`.
4. Add capability inference if it doesn't fit the existing heuristics.

## Adding a skill

Create `skills/<name>/skill.json`:

```json
{
  "name": "my_skill",
  "version": "0.1.0",
  "description": "What this skill does",
  "tools": ["my.new_tool"],
  "enabled": true
}
```

The skill registry picks it up at boot.

## Coding standards

* Strict mode by default; type hints required for new modules.
* Public functions get docstrings.
* All tool args validated through `Tool.__call__`.
* No raw `os.remove` / `shutil.rmtree` in tool code — go through
  `cheryy.security.interceptor().assert_path_safe(...)` first.
* No fake implementations — every claimed capability has a real handler
  and a test.
