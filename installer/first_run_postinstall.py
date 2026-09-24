"""First-run bootstrap script.

This is invoked automatically by the CHERYY installer on Windows.
It creates the user's data dir, verifies Python is callable, and reports
any missing dependencies in plain English (so the user doesn't see a stack
trace).
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

REPORT_PATH = Path(os.environ.get("CHERYY_DATA_DIR", str(Path.home() / "AppData" / "Local" / "CHERYY"))) / "first_run_report.json"


def _check(name: str, importable_name: str | None = None) -> dict:
    mod = importable_name or name
    try:
        __import__(mod)
        return {"name": name, "ok": True}
    except Exception as e:
        return {"name": name, "ok": False, "error": str(e)[:200]}


def main() -> int:
    report = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "checks": [],
    }
    for n, m in [
        ("pydantic", "pydantic"),
        ("httpx", "httpx"),
        ("fastapi", "fastapi"),
        ("playwright", "playwright"),
        ("python-docx", "docx"),
        ("python-pptx", "pptx"),
        ("openpyxl", "openpyxl"),
        ("reportlab", "reportlab"),
        ("pdfplumber", "pdfplumber"),
        ("pywinauto", "pywinauto"),
        ("pyautogui", "pyautogui"),
        ("mss", "mss"),
        ("Pillow", "PIL"),
        ("keyring", "keyring"),
        ("cryptography", "cryptography"),
    ]:
        report["checks"].append(_check(n, m))

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    failed = [c for c in report["checks"] if not c["ok"]]
    if failed:
        print(f"[cheryy] {len(failed)} optional dependency warning(s):")
        for f in failed:
            print(f"  - {f['name']}: {f['error']}")
    print(f"[cheryy] first-run report: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)