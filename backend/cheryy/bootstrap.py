"""Bootstrap script: starts the CHERYY backend HTTP server."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Allow `python -m cheryy.bootstrap` from `backend/`.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from cheryy.api import app  # noqa: E402
from cheryy.logging_setup import configure_logging, get_logger  # noqa: E402

log = get_logger("cheryy.bootstrap")


def main() -> None:
    parser = argparse.ArgumentParser(prog="cheryy-server")
    parser.add_argument("--host", default=os.environ.get("CHERYY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CHERYY_PORT", "7480")))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    configure_logging()
    log.info("CHERYY backend starting on http://%s:%d", args.host, args.port)
    uvicorn.run(
        "cheryy.api:app" if args.reload else app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()