"""Skill registry.

Skills bundle related tools, prompts, and validators so they can be enabled
or disabled together. The bundled manifest covers the office/browsing/
publishing/memory families and is loaded from the `skills/` tree.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ..db import session_scope, now_iso
from ..logging_setup import get_logger
from ..tools import ToolSpec, get_tool_registry

log = get_logger("cheryy.skills")


@dataclass
class Skill:
    name: str
    version: str
    description: str
    tools: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    source: str | None = None
    enabled: bool = True
    manifest: dict[str, Any] = field(default_factory=dict)


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def enabled(self) -> list[Skill]:
        return [s for s in self._skills.values() if s.enabled]

    async def persist(self) -> None:
        async with session_scope() as s:
            for sk in self._skills.values():
                await s.execute(text(
                    "INSERT INTO skills (name, version, enabled, source, manifest, installed_at) "
                    "VALUES (:n, :v, :en, :src, :m, :now) "
                    "ON CONFLICT(name) DO UPDATE SET version=excluded.version, enabled=excluded.enabled, manifest=excluded.manifest"
                ), {
                    "n": sk.name,
                    "v": sk.version,
                    "en": 1 if sk.enabled else 0,
                    "src": sk.source or "",
                    "m": json.dumps(sk.manifest),
                    "now": now_iso(),
                })

    def tool_specs_for_enabled(self) -> list[ToolSpec]:
        registry = get_tool_registry()
        specs: list[ToolSpec] = []
        enabled_tool_names = set()
        for sk in self._skills.values():
            if not sk.enabled:
                continue
            enabled_tool_names.update(sk.tools)
        for t in registry.all():
            if t.name in enabled_tool_names:
                specs.append(t.spec())
        return specs


def load_manifest(path: Path) -> Skill | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Skill(
            name=data["name"],
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            tools=data.get("tools", []),
            prompts=data.get("prompts", []),
            examples=data.get("examples", []),
            source=str(path),
            enabled=bool(data.get("enabled", True)),
            manifest=data,
        )
    except Exception as e:  # pragma: no cover
        log.warning("could not load skill manifest %s: %s", path, e)
        return None


def load_from_directory(root: Path) -> list[Skill]:
    if not root.exists():
        return []
    out: list[Skill] = []
    for child in sorted(root.iterdir()):
        manifest = child / "skill.json"
        if manifest.is_file():
            sk = load_manifest(manifest)
            if sk is not None:
                out.append(sk)
    return out


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        # Built-in default skills
        defaults: list[Skill] = [
            Skill(name="office", version="0.1", description="Office document generation", tools=[
                "office.create_docx", "office.create_pptx", "office.create_xlsx", "office.create_pdf"]),
            Skill(name="browser", version="0.1", description="Browser automation via Playwright", tools=[
                "browser.open", "browser.navigate", "browser.read", "browser.click", "browser.type",
                "browser.select", "browser.upload", "browser.download", "browser.screenshot"]),
            Skill(name="windows", version="0.1", description="Windows computer control", tools=[
                "computer.get_screen", "computer.get_windows", "computer.get_active_window", "computer.get_ui_tree",
                "computer.move_mouse", "computer.click", "computer.double_click", "computer.right_click",
                "computer.drag", "computer.scroll", "computer.type", "computer.hotkey"]),
            Skill(name="content", version="0.1", description="Writing and SEO", tools=[
                "content.blog", "content.seo", "content.write", "content.summarize"]),
            Skill(name="publishing", version="0.1", description="External publishing integrations", tools=[
                "publisher.wordpress_publish", "publisher.generic_api"]),
            Skill(name="filesystem", version="0.1", description="Safe file operations (no delete)", tools=[
                "filesystem.list", "filesystem.search", "filesystem.read", "filesystem.create",
                "filesystem.edit", "filesystem.copy", "filesystem.move", "filesystem.rename", "filesystem.open"]),
            Skill(name="image", version="0.1", description="Image generation and processing", tools=[
                "image.generate", "image.resize", "image.convert"]),
            Skill(name="voice", version="0.1", description="Voice and transcript coordination", tools=[]),
            Skill(name="memory", version="0.1", description="Persistent user memory", tools=[]),
        ]
        for sk in defaults:
            _registry.register(sk)
    return _registry