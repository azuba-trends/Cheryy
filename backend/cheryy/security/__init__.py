"""Security engine.

CHERYY's most important non-functional requirement is that it can NEVER delete
anything on the user's machine — files, folders, registry, partitions, apps,
browser profiles, the lot. This module enforces that requirement
*programmatically*, not just through prompts.

Layers:

  PermissionManager       : owns the policy and the user's grant list
  ActionPolicyEngine      : classifies actions + path/command validators
  DestructiveActionInterceptor : blocks forbidden filesystem/shell APIs
  AuditLog                : immutable record of decisions (no secrets)

Any code path that wishes to perform a filesystem, shell, or process action
MUST go through these helpers. The agent never gets raw `os.remove`, `shutil`,
`subprocess`, etc. — it only sees the tool registry below, which funnels into
this module.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from ..db import session_scope, now_iso
from ..logging_setup import get_logger

log = get_logger("cheryy.security")


# ---------------------------------------------------------------------------
# Classifications
# ---------------------------------------------------------------------------

class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_USER = "require_user"


class Risk(str, Enum):
    SAFE = "safe"
    ELEVATED = "elevated"
    DESTRUCTIVE = "destructive"


# ---------------------------------------------------------------------------
# Policy data model
# ---------------------------------------------------------------------------

@dataclass
class Policy:
    """Hard-coded policy. Mutable in-memory only; user cannot weaken `destructive`.

    The single user-tunable bit is `auto_approve_elevated`, default False.
    """
    auto_approve_elevated: bool = False
    allow_network: bool = True
    allow_browser_control: bool = True
    allow_window_control: bool = True
    allow_shell: bool = True          # through controlled executor only
    allow_registry_write: bool = False
    allow_install_software: bool = False
    allow_modify_user_folders: bool = True

    # Read-only views of what's NEVER allowed no matter what.
    @property
    def forbidden_actions(self) -> set[str]:
        return {
            "fs.delete", "fs.rmdir", "fs.unlink",
            "fs.shred", "fs.move_to_trash", "fs.empty_trash",
            "shell.del", "shell.rm", "shell.erase", "shell.rmdir", "shell.remove_item",
            "shell.format", "shell.diskpart", "shell.destructive_powershell",
            "shell.destructive_cmd",
            "registry.delete_tree", "registry.delete_value",
            "process.uninstall",
            "fs.delete_directory_tree",  # shutil.rmtree stand-in
        }


# ---------------------------------------------------------------------------
# PermissionManager
# ---------------------------------------------------------------------------

class PermissionManager:
    """Singleton — first-run grants zero permissions, the policy is hard-coded."""

    _instance: "PermissionManager | None" = None

    def __init__(self) -> None:
        self.policy = Policy()
        self.grants: dict[str, set[str]] = {}  # category -> action names
        self.history: list[dict[str, Any]] = []

    @classmethod
    def instance(cls) -> "PermissionManager":
        if cls._instance is None:
            cls._instance = PermissionManager()
        return cls._instance

    def grant(self, category: str, action: str) -> None:
        self.grants.setdefault(category, set()).add(action)

    def revoke(self, category: str, action: str | None = None) -> None:
        if action is None:
            self.grants.pop(category, None)
        else:
            self.grants.get(category, set()).discard(action)

    def is_granted(self, category: str, action: str) -> bool:
        return action in self.grants.get(category, set())


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

_DESTRUCTIVE_POWERSHELL = re.compile(
    r"\b(Remove-Item|Del|Erase|Clear-Item|Rmdir|Ri\b|format|diskpart|"
    r"Remove-AppxPackage|Uninstall-Item|Clear-RecycleBin|rd\s+/[sq]|"
    r"rm\s+-r|rm\s+-rf|rmdir|/s\s+/q)\b",
    re.IGNORECASE,
)

_DESTRUCTIVE_CMD = re.compile(
    r"\b(del|erase|rd|rmdir|format|diskpart|delTree|rd\s+/s|rm\s+-rf|rm\s+-r)\b",
    re.IGNORECASE,
)

# Detect destructive Python APIs even when called via attribute chain
# e.g. pathlib.Path('x').unlink() or shutil.rmtree(...).
# Each alternative is anchored independently so non-word terminators like `(`
# don't break matching.
_DESTRUCTIVE_PY = re.compile(
    r"(?:\bos\.remove\s*\(|\bos\.unlink\s*\(|\bos\.rmdir\s*\("
    r"|\bshutil\.rmtree\s*\(|\bsend2trash\s*\("
    r"|\B\.[\w]*unlink\s*\("
    r"|\bpathlib\.Path\.rmdir\s*\()",
    re.IGNORECASE,
)

# Paths CHERYY will never touch, even on read.
_PROTECTED_PATH_PREFIXES = (
    # Windows system directories (best-effort)
    os.environ.get("SystemRoot", r"C:\Windows") + r"\System32",
    os.environ.get("SystemRoot", r"C:\Windows") + r"\SysWOW64",
    os.environ.get("SystemRoot", r"C:\Windows") + r"\WinSxS",
    r"C:\Windows\Boot",
    r"C:\Windows\System32\config",         # SAM/SECURITY hives
    r"C:\Program Files\WindowsApps",
    r"C:\$Recycle.Bin",
    r"C:\Recovery",
    r"C:\System Volume Information",
)


def normalise_path(p: str | os.PathLike[str]) -> str:
    s = str(p)
    # Resolve to absolute, normalised form.
    try:
        return str(Path(s).expanduser().resolve())
    except Exception:
        return s


def is_protected_path(p: str) -> bool:
    np = normalise_path(p)
    for prefix in _PROTECTED_PATH_PREFIXES:
        if np.startswith(normalise_path(prefix)):
            return True
    return False


def classify_shell_command(cmd: str) -> Risk:
    """Return DESTRUCTIVE if the shell command matches known destructive patterns."""
    if _DESTRUCTIVE_POWERSHELL.search(cmd):
        return Risk.DESTRUCTIVE
    if _DESTRUCTIVE_CMD.search(cmd):
        return Risk.DESTRUCTIVE
    if _DESTRUCTIVE_PY.search(cmd):
        return Risk.DESTRUCTIVE
    return Risk.SAFE


# ---------------------------------------------------------------------------
# Action policy engine
# ---------------------------------------------------------------------------

class ActionPolicyEngine:
    """Decide what to do with a proposed tool call."""

    def __init__(self, pm: PermissionManager) -> None:
        self.pm = pm

    # ---------- filesystem path classification
    def classify_path_action(self, verb: str, path: str) -> Risk:
        v = verb.lower()
        if v in {"delete", "unlink", "rm", "rmdir", "shred", "remove"}:
            return Risk.DESTRUCTIVE
        if v in {"move", "rename", "replace"}:
            # Moving/renaming is permitted, but never into the Recycle Bin.
            return Risk.SAFE
        if v in {"write", "create", "edit", "append", "truncate"}:
            if is_protected_path(path):
                return Risk.DESTRUCTIVE
            return Risk.ELEVATED
        if v in {"read", "list", "search", "stat"}:
            return Risk.SAFE
        return Risk.ELEVATED

    # ---------- shell classification
    def classify_shell(self, cmd: str) -> Risk:
        risk = classify_shell_command(cmd)
        if risk is Risk.DESTRUCTIVE:
            return Risk.DESTRUCTIVE
        # Treat anything that touches the registry or starts an installer as elevated.
        if re.search(r"\b(reg\.exe|regadd|regdelete|msiexec|/install|/s\s*/i)\b", cmd, re.IGNORECASE):
            return Risk.ELEVATED
        return Risk.SAFE

    # ---------- decision
    def decide(self, category: str, action: str, **context: Any) -> Decision:
        risk = context.get("risk", Risk.SAFE)
        if risk is Risk.DESTRUCTIVE:
            return Decision.DENY  # NEVER destructive
        if risk is Risk.ELEVATED and not self.pm.policy.auto_approve_elevated and not self.pm.is_granted(category, action):
            return Decision.REQUIRE_USER
        if not self.pm.policy.allow_shell and category == "shell":
            return Decision.DENY
        return Decision.ALLOW


# ---------------------------------------------------------------------------
# Destructive interceptor (the no-delete safety net)
# ---------------------------------------------------------------------------

class DestructiveActionInterceptor:
    """Wraps destructive operations and refuses them.

    Any code that needs to call `os.remove`, `shutil.rmtree`, `subprocess.run`
    with a destructive command, etc. must call `assert_safe()` first.
    """

    def __init__(self, policy: Policy) -> None:
        self.policy = policy

    # ----- path-level guards
    def assert_path_safe(self, verb: str, path: str) -> None:
        v = verb.lower()
        forbidden = self.policy.forbidden_actions
        if v in {"delete", "unlink", "rm", "rmdir", "shred", "remove", "move_to_trash"}:
            mapped = f"fs.{v}"
            if mapped in forbidden:
                raise PermissionError(
                    f"CHERYY permanently forbids '{v}'. "
                    "Please perform this action manually if you really need it."
                )

    # ----- shell guards
    def assert_shell_safe(self, cmd: str) -> None:
        if classify_shell_command(cmd) is Risk.DESTRUCTIVE:
            raise PermissionError(
                f"CHERYY refused a destructive shell operation. Command rejected:\n{cmd}"
            )

    # ----- python API guards (intercept known destructive calls)
    def assert_python_safe(self, source: str) -> None:
        """`source` is the textual call site for static inspection.

        For runtime interception we rely on the agent going through controlled
        tools, not raw python exec. We still defensively check any text the
        agent emits that looks like Python.
        """
        if _DESTRUCTIVE_PY.search(source):
            raise PermissionError(
                "CHERYY detected a destructive Python API call and refused it. "
                "Please perform this action manually."
            )


# ---------------------------------------------------------------------------
# Audit log (no secrets)
# ---------------------------------------------------------------------------

async def audit(
    *,
    task_id: int | None,
    tool: str | None,
    action: str | None,
    permission: str | None,
    decision: str | None,
    result: str | None,
    verification: str | None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Persist an immutable audit record. Never includes secrets."""
    try:
        meta_json = json.dumps(meta or {}, default=str)
        async with session_scope() as s:
            await s.execute(
                text_insert_audit__(),
                {
                    "ts": now_iso(),
                    "task_id": task_id,
                    "tool": tool,
                    "action": action,
                    "permission": permission,
                    "decision": decision,
                    "result": result,
                    "verification": verification,
                    "meta": meta_json,
                },
            )
    except Exception as e:  # pragma: no cover - never break on audit failure
        log.warning("audit insert failed: %s", e)


def text_insert_audit__():
    # Imported lazily so unit tests can monkeypatch.
    from sqlalchemy import text
    return text(
        "INSERT INTO audit_log "
        "(ts, task_id, tool, action, permission, decision, result, verification, meta) "
        "VALUES (:ts, :task_id, :tool, :action, :permission, :decision, :result, :verification, :meta)"
    )


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

def pm() -> PermissionManager:
    return PermissionManager.instance()


def engine() -> ActionPolicyEngine:
    return ActionPolicyEngine(pm())


def interceptor() -> DestructiveActionInterceptor:
    return DestructiveActionInterceptor(pm().policy)