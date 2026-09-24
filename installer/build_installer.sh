#!/usr/bin/env bash
# CHERYY headless build for CI / Linux dev containers.
#
# This is mostly a convenience wrapper used by CI; the real production
# installer is built on a Windows host via `build_installer.ps1`.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
DESKTOP="$ROOT/desktop"

echo "==> Backend"
cd "$BACKEND"
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev] pyinstaller
pyinstaller --noconfirm --clean --name cheryy-server cheryy/bootstrap.py

echo "==> Desktop UI"
cd "$DESKTOP"
npm ci || npm install
npm run build

echo "==> Done."
