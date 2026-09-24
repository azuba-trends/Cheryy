# CHERYY Security model

> _The "never delete anything" rule is enforced programmatically, not by prompt._

## Hard rules

1. **No-delete** — this is permanent. See [`cheryy/security/__init__.py`](../backend/cheryy/security/__init__.py).
2. **No system mutation** outside user folders without explicit user approval.
3. **No destructive registry writes.**
4. **No uninstall or system wipe.**
5. **No file/folder deletion by any verb** (rm, unlink, del, shred, erase, rmtree).

## How it's enforced

* `cheryy.security.Policy.forbidden_actions` is the immutable set of forbidden
  verbs.
* `cheryy.security.DestructiveActionInterceptor` rejects every form of
  destructive operation at *the lowest layer*, not just at the AI prompt
  level. Even if an attacker fully controls the LLM output they cannot
  delete a file via a registered tool.
* `cheryy.security.ActionPolicyEngine.decide(...)` classifies the *risk*
  (SAFE / ELEVATED / DESTRUCTIVE) of a proposed action from:
  - the tool's static `destructive` flag
  - the path (protected Windows paths)
  - the shell command (regex match against destructive PowerShell / CMD / Python tokens)
  DESTRUCTIVE risk is ALWAYS denied — granted permissions cannot override it.
* `cheryy.tools` requires every tool to pass through a `Tool.__call__` gate.
* Every action is recorded in `audit_log` (no secrets recorded).

## What's allowed without user approval

* Reading user folders (Documents, Desktop, Pictures, Videos, Downloads, Music).
* Listing windows / screenshots.
* TTS / STT (audio playback requires no elevated permissions).
* Network calls to authorised API endpoints (Gemini / user-added publishing services).

## What requires user approval (elevated)

* Writing under directories outside the safe roots.
* Opening arbitrary shell commands (even when not destructive).
* Connecting to publishing services (WordPress, etc).
* Adjusting skill permissions at runtime.

## What is **permanently forbidden**

* All filesystem deletions of any kind, including Recycle Bin.
* `format`, `diskpart`, registry destruction, uninstall.
* `rmdir /s`, `rmdir /q`, `del /f`, `del /s`.
* `os.remove`, `os.unlink`, `os.rmdir`, `shutil.rmtree`, `pathlib.Path.unlink`,
  `send2trash`.
* Any destructive Python statement emitted as text by the agent.

## Tests that prove this

* `backend/tests/test_security.py` — static, exhaustive.
* `backend/tests/test_filesystem.py::test_no_delete_tool_registered` — runtime.

These tests will fail if anyone adds a destructive tool without the proper
guard, so the guarantee is preserved across future development.
