"""Publishing integrations.

CHERYY ships with a working WordPress publisher (Application Password auth) and
a generic-API publisher. External services are *always* optional — they only
kick in after the user explicitly authorises them in Settings.

Validation flow: Prepare → Upload → Fill → Preview → Verify → Publish → Verify.
We never claim a publication unless the API response confirms it.
"""
from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from ..logging_setup import get_logger
from ..secrets import get_secret_store
from ..tools import ToolResult, tool

log = get_logger("cheryy.publishing")


def _wp_creds() -> tuple[str | None, str | None, str | None]:
    store = get_secret_store()
    base = store.get("wp_base_url")
    user = store.get("wp_username")
    pwd = store.get("wp_app_password")
    return base, user, pwd


@tool(
    name="publisher.wordpress_publish",
    description="Publish a post to WordPress using REST API + Application Password. Requires user authorisation in Settings.",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content_html": {"type": "string"},
            "status": {"type": "string", "enum": ["draft", "publish"], "default": "draft"},
            "featured_image_path": {"type": "string"},
            "meta_title": {"type": "string"},
            "meta_description": {"type": "string"},
        },
        "required": ["title", "content_html"],
    },
    category="publishing",
)
async def wp_publish(
    title: str,
    content_html: str,
    status: str = "draft",
    featured_image_path: str | None = None,
    meta_title: str | None = None,
    meta_description: str | None = None,
) -> dict[str, Any]:
    base, user, pwd = _wp_creds()
    if not (base and user and pwd):
        return {"error": "WordPress credentials missing. Add them in Settings → Publishing."}
    auth = httpx.BasicAuth(user, pwd)

    async with httpx.AsyncClient(timeout=60, auth=auth) as c:
        media_id = None
        if featured_image_path:
            from pathlib import Path
            mime = "image/jpeg" if featured_image_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
            with open(featured_image_path, "rb") as f:
                r = await c.post(
                    f"{base.rstrip('/')}/wp-json/wp/v2/media",
                    headers={"Content-Disposition": f'attachment; filename="{Path(featured_image_path).name}"', "Content-Type": mime},
                    content=f.read(),
                )
            r.raise_for_status()
            j = r.json()
            media_id = j.get("id")

        post = {
            "title": title,
            "content": content_html,
            "status": status,
            "excerpt": meta_description or "",
        }
        if media_id:
            post["featured_media"] = media_id
        if meta_title:
            post["meta"] = {"yoast_wpseo_title": meta_title}  # type: ignore[assignment]

        r = await c.post(f"{base.rstrip('/')}/wp-json/wp/v2/posts", json=post)
        r.raise_for_status()
        result = r.json()
        return {
            "ok": True,
            "id": result.get("id"),
            "link": result.get("link"),
            "status": result.get("status"),
            "featured_media": media_id,
        }


@tool(
    name="publisher.generic_api",
    description="POST a JSON payload to an authorised web endpoint with a stored bearer token.",
    parameters={
        "type": "object",
        "properties": {
            "endpoint_key": {"type": "string"},
            "path": {"type": "string"},
            "payload": {"type": "object"},
        },
        "required": ["endpoint_key", "path", "payload"],
    },
    category="publishing",
)
async def generic_api(endpoint_key: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = get_secret_store().get(f"endpoint::{endpoint_key}::base")
    token = get_secret_store().get(f"endpoint::{endpoint_key}::token")
    if not base:
        return {"error": f"endpoint '{endpoint_key}' not configured"}
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = base.rstrip("/") + path
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return {"ok": True, "status": r.status_code, "response": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:2000]}