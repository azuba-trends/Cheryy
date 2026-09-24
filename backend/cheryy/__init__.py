"""CHERYY backend package.

The runtime is designed around a small set of orthogonal modules:
- providers   (LLM, vision, voice, embeddings, image)
- security    (no-delete enforcement + audit)
- memory      (six-category memory with retrieval)
- tasks       (autonomous task engine with checkpoints)
- tools       (structured tool registry exposed to the agent)
- computer    (Windows UI automation, screen, mouse, keyboard)
- browser     (Playwright-based DOM automation)
- office      (DOCX / PPTX / XLSX / PDF generators)
- voice       (Live, TTS, STT, barge-in)
- publishing  (WordPress, generic APIs)
- scheduler   (event-driven local scheduler)
- skills      (extensible skill registry)
- api         (FastAPI HTTP/WS surface for the desktop UI)
"""

__version__ = "0.1.0"
__all__ = ["__version__"]