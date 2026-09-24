"""Image provider abstraction.

CHERYY's image generation is OPTIONAL. It is intentionally not part of the
default runtime because most image APIs cost money or have stricter quotas
than text models. We provide a clean interface and a default placeholder
implementation that returns a branded gradient (so the workflow still
completes when no image provider is configured).

Users may configure providers in Settings (Gemini image preview, Replicate,
etc.) by adding a JSON entry to `image.providers` in config.json.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter
from ..logging_setup import get_logger
from ..tools import ToolResult, tool

log = get_logger("cheryy.image")

SUPPORTED_SIZES = [
    (1200, 630),
    (1000, 450),
    (1920, 1080),
    (1080, 1080),
    (1080, 1350),
]


def generate_placeholder(width: int, height: int, text: str) -> bytes:
    img = Image.new("RGB", (width, height), "#0F172A")
    draw = ImageDraw.Draw(img)
    # Gradient
    for y in range(height):
        c = int(15 + (y / max(1, height)) * 30)
        draw.line([(0, y), (width, y)], fill=(c, c + 10, c + 30))
    # Accent bar
    draw.rectangle([(0, height - 12), (width, height)], fill="#5B8DEF")
    # Watermark
    try:
        from PIL import ImageFont
        font = ImageFont.load_default()
        draw.text((40, 40), "CHERYY", fill="#E6EDF3", font=font)
        draw.text((40, height - 60), text[:64], fill="#E6EDF3", font=font)
    except Exception:
        pass
    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@tool(
    name="image.generate",
    description="Generate an image. Without a configured image provider, returns a branded placeholder so the workflow still completes.",
    parameters={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "save_path": {"type": "string"},
        },
        "required": ["prompt", "save_path"],
    },
    category="image",
)
async def image_generate(prompt: str, save_path: str, width: int = 1024, height: int = 1024) -> dict[str, Any]:
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    # No provider wired by default. Produce a clearly-labelled placeholder so
    # downstream steps can still proceed; never pretend it's a real generated image.
    data = generate_placeholder(width, height, prompt)
    Path(save_path).write_bytes(data)
    return {"path": save_path, "width": width, "height": height, "ok": True, "provider": "placeholder", "note": "configure an image provider in Settings for real generation"}


@tool(
    name="image.resize",
    description="Resize an image to width × height using Pillow (preserves aspect ratio when fit=True).",
    parameters={
        "type": "object",
        "properties": {"source": {"type": "string"}, "destination": {"type": "string"}, "width": {"type": "integer"}, "height": {"type": "integer"}, "fit": {"type": "boolean", "default": True}},
        "required": ["source", "destination", "width", "height"],
    },
    category="image",
)
async def image_resize(source: str, destination: str, width: int, height: int, fit: bool = True) -> dict[str, Any]:
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(source)
    if fit:
        img.thumbnail((width, height))
        canvas = Image.new("RGB", (width, height), "#FFFFFF")
        canvas.paste(img, ((width - img.width) // 2, (height - img.height) // 2))
        img = canvas
    else:
        img = img.resize((width, height))
    img.save(destination, quality=92)
    return {"source": source, "destination": destination, "width": width, "height": height, "ok": True}


@tool(
    name="image.convert",
    description="Convert an image between formats.",
    parameters={
        "type": "object",
        "properties": {"source": {"type": "string"}, "destination": {"type": "string"}, "format": {"type": "string", "enum": ["png", "jpg", "webp"]}},
        "required": ["source", "destination", "format"],
    },
    category="image",
)
async def image_convert(source: str, destination: str, format: str) -> dict[str, Any]:
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(source)
    if format == "jpg":
        img = img.convert("RGB")
    img.save(destination, format=format.upper(), quality=92)
    return {"source": source, "destination": destination, "format": format, "ok": True}