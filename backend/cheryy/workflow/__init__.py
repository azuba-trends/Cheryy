"""Reusable workflow storage.

When the user repeatedly asks for the same kind of task, CHERYY can save a
*workflow* that names the steps, required tools, required permissions and
variables. Saved workflows are exposed as macros in Settings → Skills and
can be replayed one-shot with `workflow.run(name, variables=...)`.

A workflow can NEVER delete anything by construction: each step references an
already-registered tool, and the same security engine decides whether the
tool may run.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text

from ..db import session_scope, now_iso
from ..logging_setup import get_logger
from ..tools import get_tool_registry

log = get_logger("cheryy.workflow")


@dataclass
class WorkflowDef:
    name: str
    description: str
    steps: list[dict[str, Any]]
    required_tools: list[str]
    required_perms: list[str]
    variables: list[dict[str, Any]] = None  # type: ignore[assignment]
    validation: list[dict[str, Any]] = None  # type: ignore[assignment]


class WorkflowRegistry:
    def __init__(self) -> None:
        self._local: dict[str, WorkflowDef] = {}

    def add(self, wf: WorkflowDef) -> None:
        self._local[wf.name] = wf

    def get(self, name: str) -> WorkflowDef | None:
        return self._local.get(name)

    def all(self) -> list[WorkflowDef]:
        return list(self._local.values())

    async def persist(self) -> None:
        async with session_scope() as s:
            for wf in self._local.values():
                await s.execute(text(
                    "INSERT INTO workflows (name, description, steps, required_tools, required_perms, variables, validation, created_at) "
                    "VALUES (:n, :d, :steps, :rt, :rp, :vars, :val, :now) "
                    "ON CONFLICT(name) DO UPDATE SET description=excluded.description, steps=excluded.steps, required_tools=excluded.required_tools, required_perms=excluded.required_perms"
                ), {
                    "n": wf.name,
                    "d": wf.description,
                    "steps": json.dumps(wf.steps),
                    "rt": json.dumps(wf.required_tools),
                    "rp": json.dumps(wf.required_perms),
                    "vars": json.dumps(wf.variables or []),
                    "val": json.dumps(wf.validation or []),
                    "now": now_iso(),
                })

    async def run(self, name: str, *, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        wf = self._local.get(name)
        if wf is None:
            return {"ok": False, "error": f"unknown workflow: {name}"}
        registry = get_tool_registry()
        results = []
        for i, step in enumerate(wf.steps):
            tool_name = step.get("tool")
            args = dict(step.get("args") or {})
            # Template substitution for simple {{var}} placeholders.
            for k, v in list(args.items()):
                if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
                    var = v[2:-2].strip()
                    if variables and var in variables:
                        args[k] = variables[var]
            tool = registry.get(tool_name) if tool_name else None
            if tool is None:
                results.append({"step": i, "tool": tool_name, "ok": False, "error": "tool not registered"})
                return {"ok": False, "workflow": name, "completed": i, "results": results}
            res = await tool(**args)
            results.append({"step": i, "tool": tool_name, "ok": res.success, "data": res.data, "error": res.error})
            if not res.success:
                return {"ok": False, "workflow": name, "completed": i, "results": results}
        return {"ok": True, "workflow": name, "completed": len(results), "results": results}


# Built-in starter workflows -------------------------------------------------

_DEFAULT_WORKFLOWS: list[WorkflowDef] = [
    WorkflowDef(
        name="blog_to_docx",
        description="Research → SEO blog → DOCX in Documents folder.",
        steps=[
            {"tool": "content.blog", "args": {"topic": "{{topic}}", "save_path": "{{md_path}}"}},
            {"tool": "office.create_docx", "args": {"path": "{{docx_path}}", "title": "{{title}}", "sections": [{"heading": "Content", "paragraphs": ["{{body}}"]}]}},
        ],
        required_tools=["content.blog", "office.create_docx"],
        required_perms=["fs.write"],
        variables=[
            {"name": "topic", "type": "string"},
            {"name": "title", "type": "string"},
            {"name": "md_path", "type": "path"},
            {"name": "docx_path", "type": "path"},
            {"name": "body", "type": "string"},
        ],
    ),
    WorkflowDef(
        name="pptx_about_topic",
        description="Generate a 10-slide PPTX about a topic and save it.",
        steps=[
            {"tool": "office.create_pptx", "args": {"path": "{{path}}", "title": "{{title}}", "slides": "{{slides}}"}},
        ],
        required_tools=["office.create_pptx"],
        required_perms=["fs.write"],
        variables=[
            {"name": "path", "type": "path"},
            {"name": "title", "type": "string"},
            {"name": "slides", "type": "json"},
        ],
    ),
]


def _install_defaults(reg: WorkflowRegistry) -> None:
    for wf in _DEFAULT_WORKFLOWS:
        reg.add(wf)


_registry: WorkflowRegistry | None = None


def get_workflow_registry() -> WorkflowRegistry:
    global _registry
    if _registry is None:
        _registry = WorkflowRegistry()
        _install_defaults(_registry)
    return _registry