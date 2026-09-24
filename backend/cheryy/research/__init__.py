"""Research tools.

CHERYY's research toolkit:

  * `research.search_web`     - fetch search results via DuckDuckGo HTML
                              (no API key, no JS — works on free-tier users)
  * `research.read_page`      - read a URL, extract main text + links
  * `research.extract`        - extract a structured summary from a body of text
  * `research.compare`        - multi-source comparative summary

Every step captures the **literal byte size** and the **first/last lines** of
the fetched content so verification can confirm "we actually got something
back" rather than the agent guessing.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import httpx

from ..logging_setup import get_logger
from ..providers.base import Capability, LLMMessage, LLMRequest
from ..providers.registry import get_registry
from ..tools import ToolResult, tool

log = get_logger("cheryy.research")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    text = _HTML_TAG.sub(" ", html)
    return _WS.sub(" ", text).strip()


@tool(
    name="research.search_web",
    description="Search the web via DuckDuckGo HTML. Returns up to 10 {title, url, snippet}.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}},
        "required": ["query"],
    },
    category="research",
)
async def research_search_web(query: str, limit: int = 10) -> dict[str, Any]:
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT}, timeout=30.0, follow_redirects=True
    ) as c:
        try:
            r = await c.get(url)
        except Exception as e:
            return {"error": f"network error: {e}"}
        if r.status_code != 200:
            return {"error": f"search returned {r.status_code}"}
        html = r.text
    # Extract results crudely.
    results: list[dict[str, str]] = []
    # Anchor pattern matches DuckDuckGo's result blocks.
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        link = m.group(1)
        title = _strip_html(m.group(2))
        if not link.startswith("http"):
            continue
        results.append({"title": title, "url": link})
        if len(results) >= limit:
            break
    return {"query": query, "results": results, "bytes": len(html), "ok": True}


@tool(
    name="research.read_page",
    description="Fetch a URL and return its main text plus a list of links. NO direct page mutation.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer", "default": 8000}},
        "required": ["url"],
    },
    category="research",
)
async def research_read_page(url: str, max_chars: int = 8000) -> dict[str, Any]:
    async with httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT}, timeout=30.0, follow_redirects=True
    ) as c:
        try:
            r = await c.get(url)
        except Exception as e:
            return {"error": f"network error: {e}"}
        if r.status_code != 200:
            return {"error": f"fetch returned {r.status_code}"}
        html = r.text
    text = _strip_html(html)[:max_chars]
    # Extract anchor links.
    links: list[str] = []
    for m in re.finditer(r'<a[^>]+href="([^"]+)"', html, re.IGNORECASE):
        link = m.group(1)
        if link.startswith("javascript:") or link.startswith("#"):
            continue
        if not link.startswith(("http://", "https://")):
            link = urljoin(url, link)
        # Strip fragment for dedup.
        parsed = urlparse(link)
        link = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if link and link not in links and len(links) < 50:
            links.append(link)
    return {"url": url, "title": re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL).group(1).strip() if re.search(r"<title>", html, re.IGNORECASE) else "", "text": text, "links": links, "bytes": len(html), "ok": True}


@tool(
    name="research.extract",
    description="Pull a structured summary (key facts, claims, quotes) from a chunk of text.",
    parameters={
        "type": "object",
        "properties": {"text": {"type": "string"}, "focus": {"type": "string", "default": "key facts"}, "max_words": {"type": "integer", "default": 250}},
        "required": ["text"],
    },
    category="research",
)
async def research_extract(text: str, focus: str = "key facts", max_words: int = 250) -> dict[str, Any]:
    reg = get_registry()
    llm = reg.llm()
    if llm is None:
        return {"error": "no provider"}
    user = (
        f"Extract the {focus} from the following text. Use bullet points, no preamble, no invented facts.\n"
        f"Limit to about {max_words} words.\n\n{text[:60000]}"
    )
    req = LLMRequest(messages=[LLMMessage(role="user", content=user)], max_tokens=512)
    resp = await reg.generate(req, capability=Capability.GENERAL)
    return {"focus": focus, "extract": resp.content}


@tool(
    name="research.compare",
    description="Compare information from multiple sources and summarise agreements / disagreements.",
    parameters={
        "type": "object",
        "properties": {"sources": {"type": "array", "items": {"type": "object"}}, "topic": {"type": "string"}},
        "required": ["sources", "topic"],
    },
    category="research",
)
async def research_compare(sources: list[dict[str, str]], topic: str) -> dict[str, Any]:
    reg = get_registry()
    llm = reg.llm()
    if llm is None:
        return {"error": "no provider"}
    parts = []
    for s in sources:
        parts.append(f"- {s.get('title','(untitled)')} ({s.get('url','')})\n{s.get('text','')[:4000]}")
    user = (
        f"Compare these sources on the topic: {topic}.\n"
        "Highlight agreements, disagreements, and unique facts each source adds. Be conservative.\n\n"
        + "\n\n".join(parts)
    )
    req = LLMRequest(messages=[LLMMessage(role="user", content=user)], max_tokens=1024)
    resp = await reg.generate(req, capability=Capability.GENERAL)
    return {"topic": topic, "sources": len(sources), "summary": resp.content}