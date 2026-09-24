"""Lightweight CLI: validate a key, run diagnostics, etc."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from cheryy.logging_setup import configure_logging
from cheryy.setup import run_self_test, validate_api_key, apply_validated_key


def cmd_validate(args: argparse.Namespace) -> int:
    async def _run():
        res = await validate_api_key(args.key)
        print(json.dumps(res, indent=2))
    asyncio.run(_run())
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    async def _run():
        res = await validate_api_key(args.key)
        if not res.get("ok"):
            print(json.dumps(res, indent=2))
            return 1
        info = await apply_validated_key(args.key)
        print(json.dumps({"ok": True, "info": info}, indent=2, default=str))
        return 0
    return asyncio.run(_run())


def cmd_selftest(args: argparse.Namespace) -> int:
    async def _run():
        r = await run_self_test()
        print(json.dumps(r, indent=2, default=str))
    asyncio.run(_run())
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="cheryy")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("validate", help="Validate a Gemini API key")
    p1.add_argument("key")
    p1.set_defaults(func=cmd_validate)

    p2 = sub.add_parser("apply", help="Validate and store a Gemini API key")
    p2.add_argument("key")
    p2.set_defaults(func=cmd_apply)

    p3 = sub.add_parser("selftest", help="Run first-run capability self test")
    p3.set_defaults(func=cmd_selftest)

    args = parser.parse_args()
    configure_logging()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()