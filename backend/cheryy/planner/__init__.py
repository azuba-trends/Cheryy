"""Planner.

Turns a natural-language request into a structured plan of steps. The plan
uses the same tool schema the agent uses, which keeps the planner honest.

We don't ask the LLM to invent tools or to call `delete`/`rm`. The prompt
includes the registered tool list (names + descriptions only — never secrets).
"""
from __future__ import annotations

import json
from typing import Any

from ..providers.base import Capability, LLMMessage, LLMRequest
from ..providers.registry import get_registry
from ..tasks import TaskStep
from ..tools import get_tool_registry
from ..logging_setup import get_logger

log = get_logger("cheryy.planner")


SYSTEM = """You are CHERYY's planner. Convert the user's request into a JSON plan of steps.
Each step has:
  index (int), description (string), tool (string|null), args (object), verification (string|null).

Constraints:
- ONLY use tools from the provided list (their names appear as 'name' below). Never invent tool names.
- NEVER include any step that deletes, moves-to-trash, uninstalls, or wipes anything.
  If a destructive action is implied by the request, omit that step and note the reason in description.
- Prefer the minimum number of steps.
- For each tool, populate args with concrete values you can infer from the request.
- If the request is purely conversational (greeting, question), return an empty plan.

Output STRICT JSON. No prose around it."""


async def plan(user_request: str, *, context: str = "") -> list[TaskStep]:
    reg = get_registry()
    if reg.llm() is None:
        return []
    tools = [{"name": t.name, "description": t.description} for t in get_tool_registry().all()]
    user = (
        f"Request: {user_request}\n\n"
        + (f"Context:\n{context}\n\n" if context else "")
        + "Available tools:\n"
        + json.dumps(tools, indent=2)
        + "\n\nReturn JSON: {\"plan\": [ {step1}, {step2}, ... ] }"
    )
    req = LLMRequest(
        messages=[LLMMessage(role="user", content=user)],
        system=SYSTEM,
        response_format_json=True,
        temperature=0.2,
        max_tokens=2048,
    )
    resp = await reg.generate(req, capability=Capability.PLANNER)
    raw = resp.content.strip()
    try:
        data = json.loads(raw)
    except Exception:
        # Heuristic fallback: find first {...} block.
        a = raw.find("{")
        b = raw.rfind("}")
        if a >= 0 and b > a:
            try:
                data = json.loads(raw[a:b + 1])
            except Exception:
                data = {"plan": []}
        else:
            data = {"plan": []}
    out: list[TaskStep] = []
    forbidden = {"fs.delete", "filesystem.delete", "delete", "rm", "shutil.rmtree"}
    for s in (data.get("plan") or []):
        if not isinstance(s, dict):
            continue
        tool = s.get("tool")
        if isinstance(tool, str) and tool.lower() in forbidden:
            continue
        out.append(TaskStep(
            index=len(out),
            description=str(s.get("description", ""))[:280],
            tool=tool if (tool is None or isinstance(tool, str)) else None,
            args=s.get("args") or {},
            verification=s.get("verification"),
        ))
    return out