"""Test config.

Tests use a *separate* data dir so we never touch the user's CHERYY data.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


# Ensure the repo's package is importable when running pytest from any cwd.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# Redirect all CHERYY data paths to a temp dir before importing the package.
_TMP = Path(tempfile.mkdtemp(prefix="cheryy-test-"))
os.environ["CHERYY_DATA_DIR"] = str(_TMP)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Per-test data directory isolation."""
    d = tmp_path / "cheryy"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CHERYY_DATA_DIR", str(d))
    # Force re-init the singletons that cache paths.
    import cheryy.config as config
    config._cached = None
    yield
