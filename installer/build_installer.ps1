# CHERYY Windows installer / build script.
# Run from PowerShell on a Windows dev machine.

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$ROOT     = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BACKEND  = Join-Path $ROOT "backend"
$DESKTOP  = Join-Path $ROOT "desktop"
$OUT      = Join-Path $ROOT "dist"
$VERSION  = "0.1.0"
$NAME     = "CHERYY"

# 1. Create venv + install backend
if (-not (Test-Path (Join-Path $BACKEND ".venv"))) {
    Write-Host "==> Creating Python venv" -ForegroundColor Cyan
    python -m venv (Join-Path $BACKEND ".venv")
}
Write-Host "==> Installing backend (editable + pyinstaller)" -ForegroundColor Cyan
& (Join-Path $BACKEND ".venv\Scripts\pip.exe") install --upgrade pip wheel setuptools | Out-Null
& (Join-Path $BACKEND ".venv\Scripts\pip.exe") install -e $BACKEND pyinstaller | Out-Null

# 2. Build the desktop UI
Write-Host "==> Building desktop UI (Vite)" -ForegroundColor Cyan
Push-Location $DESKTOP
if (-not (Test-Path node_modules)) { npm install }
npm run build
Pop-Location

# 3. Bundle backend with PyInstaller
Write-Host "==> Bundling backend with PyInstaller" -ForegroundColor Cyan
$specDir = Join-Path $OUT "pyi"
New-Item -ItemType Directory -Force -Path $specDir | Out-Null
Push-Location $BACKEND
& (Join-Path $BACKEND ".venv\Scripts\pyinstaller.exe") `
    --noconfirm `
    --clean `
    --windowed `
    --name cheryy-server `
    --distpath (Join-Path $OUT "pyi\dist") `
    --workpath (Join-Path $OUT "pyi\build") `
    --specpath $specDir `
    (Join-Path $BACKEND "cheryy\bootstrap.py") | Out-Null
Pop-Location

# 4. Run Tauri to produce the Windows installer
Write-Host "==> Building Tauri shell (MSI + NSIS)" -ForegroundColor Cyan
Push-Location (Join-Path $DESKTOP "src-tauri")
# Tauri expects a target/ folder for icons etc.
if (-not (Test-Path icons)) { New-Item -ItemType Directory -Force -Path icons | Out-Null }
# Copy the bundled backend binary into a sidecar path the Tauri shell will look up
Copy-Item -Force (Join-Path $OUT "pyi\dist\cheryy-server\cheryy-server.exe") (Join-Path $DESKTOP "src-tauri\cheryy-server.exe") -ErrorAction SilentlyContinue
npx --yes @tauri-apps/cli@1.5 build
Pop-Location

Write-Host "==> Done." -ForegroundColor Green
Write-Host "    Installer output: $DESKTOP\src-tauri\target\release\bundle\"
