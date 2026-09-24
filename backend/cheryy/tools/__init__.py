"""Tool registry.

Each tool:
  - has a stable name + JSON-schema parameters
  - declares a permission category (e.g. 'fs', 'computer', 'office')
  - declares whether it ever performs a DESTRUCTIVE action
  - returns a structured result dataclass (success / data / verification / recovery)

Tools are the ONLY way the agent can touch the computer. The registry is
where the security engine gets to veto.
"""
from __future__ import annotations

import asyncio
import inspect as _inspect
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

from ..logging_setup import get_logger
from ..security import (
    Decision,
    Risk,
    audit,
    engine,
    interceptor,
    pm,
)
from ..providers.base import ToolSpec

log = get_logger("cheryy.tools")


@dataclass
class ToolResult:
    success: bool
    tool: str
    data: Any = None
    error: str | None = None
    verification: bool = False
    observed_state: str | None = None
    recovery: list[str] = field(default_factory=list)
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Don't dump big binary payloads to logs
        if isinstance(d.get("data"), (bytes, bytearray)):
            d["data"] = f"<{len(d['data'])} bytes>"
        return d


class Tool:
    """Descriptor + executor for a single tool."""

    def __init__(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
        category: str,
        destructive: bool = False,
        elevated: bool = False,
        handler: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.category = category
        self.destructive = destructive
        self.elevated = elevated
        self.handler = handler

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            requires_confirmation=self.elevated,
        )

    async def __call__(self, **kwargs: Any) -> ToolResult:
        if self.handler is None:
            return ToolResult(False, self.name, error="handler not bound")
        decision = self._gate(kwargs)
        t0 = time.time()
        if decision is Decision.DENY:
            await audit(
                task_id=kwargs.pop("_task_id", None),
                tool=self.name,
                action=self.name,
                permission=self.category,
                decision="deny",
                result=None,
                verification=None,
                meta={"kwargs": _safe_meta(kwargs)},
            )
            return ToolResult(False, self.name, error="permission denied by security engine")
        try:
            out = await self.handler(**kwargs)
            if isinstance(out, ToolResult):
                out.tool = self.name
                out.latency_ms = int((time.time() - t0) * 1000)
                result = out
            else:
                result = ToolResult(True, self.name, data=out, latency_ms=int((time.time() - t0) * 1000))
        except PermissionError as e:
            await audit(
                task_id=kwargs.pop("_task_id", None),
                tool=self.name,
                action=self.name,
                permission=self.category,
                decision="deny",
                result=None,
                verification=None,
                meta={"error": str(e), "kwargs": _safe_meta(kwargs)},
            )
            return ToolResult(False, self.name, error=str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("tool %s failed", self.name)
            return ToolResult(False, self.name, error=str(e), latency_ms=int((time.time() - t0) * 1000))

        await audit(
            task_id=kwargs.pop("_task_id", None),
            tool=self.name,
            action=self.name,
            permission=self.category,
            decision="allow",
            result="ok" if result.success else "fail",
            verification="ok" if result.verification else None,
            meta={"kwargs": _safe_meta(kwargs)},
        )
        return result

    def _gate(self, kwargs: dict[str, Any]) -> Decision:
        eng = engine()
        # Hard veto: destructive tools are NEVER allowed.
        if self.destructive:
            return Decision.DENY
        # Specific check for shell-style verbs
        if self.category == "shell":
            cmd = kwargs.get("command") or kwargs.get("cmd") or ""
            if cmd:
                return eng.decide(self.category, self.name, risk=eng.classify_shell(cmd))
        if self.category == "fs":
            verb = kwargs.get("verb") or self.name.split(".")[-1]
            path = kwargs.get("path") or ""
            if path:
                return eng.decide(self.category, self.name, risk=eng.classify_path_action(verb, path))
        # Generic
        risk = Risk.ELEVATED if self.elevated else Risk.SAFE
        return eng.decide(self.category, self.name, risk=risk)


def _safe_meta(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Strip large / sensitive values before auditing."""
    out: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k.startswith("_"):
            continue
        if isinstance(v, (bytes, bytearray)):
            out[k] = f"<{len(v)} bytes>"
        elif isinstance(v, str) and len(v) > 240:
            out[k] = v[:240] + "…"
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            log.warning("duplicate tool registration: %s", tool.name)
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    async def invoke(self, name: str, **kwargs: Any) -> ToolResult:
        t = self._tools.get(name)
        if not t:
            return ToolResult(False, name, error=f"unknown tool: {name}")
        return await t(**kwargs)


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def tool(
    *,
    name: str,
    description: str,
    parameters: dict[str, Any],
    category: str,
    destructive: bool = False,
    elevated: bool = False,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator for ergonomic tool registration."""

    def _wrap(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        t = Tool(
            name=name,
            description=description,
            parameters=parameters,
            category=category,
            destructive=destructive,
            elevated=elevated,
            handler=fn,
        )
        get_tool_registry().register(t)
        return fn

    return _wrap