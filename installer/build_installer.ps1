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

# IMPORTANT: this script runs under Windows PowerShell 5.1 in CI
# (`powershell.exe`, not `pwsh`). 5.1 does NOT honour
# `$PSNativeCommandUseErrorActionPreference`. We must therefore check
# `$LASTEXITCODE` explicitly after every native-command call so failures
# surface loudly to the caller (GitHub Actions / `pwsh` / dev terminal).

function Assert-LastExitCode {
    param(
        [Parameter(Mandatory = $true)] [string] $StepName,
        [int] $Allowed = 0
    )
    if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -notin $Allowed) {
        throw "$StepName failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Step {
    # Wraps a native command so its output streams AND the exit code is checked.
    # Without this, | Out-Null would hide output but the script would also lose
    # error propagation on PowerShell 5.1.
    param(
        [Parameter(Mandatory = $true)] [string] $StepName,
        [Parameter(Mandatory = $true)] [scriptblock] $Block
    )
    Write-Host "==> $StepName" -ForegroundColor Cyan
    & $Block
    Assert-LastExitCode -StepName $StepName
}

# 1. Create venv + install backend
if (-not (Test-Path (Join-Path $BACKEND ".venv"))) {
    Write-Host "==> Creating Python venv" -ForegroundColor Cyan
    python -m venv (Join-Path $BACKEND ".venv")
}
Invoke-Step "pip self-update" {
    & (Join-Path $BACKEND ".venv\Scripts\pip.exe") install --upgrade pip wheel setuptools
}
Invoke-Step "Install backend (editable) + pyinstaller" {
    & (Join-Path $BACKEND ".venv\Scripts\pip.exe") install -e $BACKEND pyinstaller
}

# 2. Build the desktop UI
Write-Host "==> Building desktop UI (Vite)" -ForegroundColor Cyan
Push-Location $DESKTOP
if (-not (Test-Path node_modules)) { npm install }
Invoke-Step "npm run build" { npm run build }
Pop-Location

# 3. Bundle backend with PyInstaller
Write-Host "==> Bundling backend with PyInstaller" -ForegroundColor Cyan
$specDir = Join-Path $OUT "pyi"
New-Item -ItemType Directory -Force -Path $specDir | Out-Null
Push-Location $BACKEND
Invoke-Step "PyInstaller" {
    & (Join-Path $BACKEND ".venv\Scripts\pyinstaller.exe") `
        --noconfirm `
        --clean `
        --windowed `
        --name cheryy-server `
        --distpath (Join-Path $OUT "pyi\dist") `
        --workpath (Join-Path $OUT "pyi\build") `
        --specpath $specDir `
        (Join-Path $BACKEND "cheryy\bootstrap.py")
}
Pop-Location

# 4. Run Tauri to produce the Windows installer
Write-Host "==> Building Tauri shell (MSI + NSIS)" -ForegroundColor Cyan
Push-Location (Join-Path $DESKTOP "src-tauri")
# Tauri expects a target/ folder for icons etc.
if (-not (Test-Path icons)) { New-Item -ItemType Directory -Force -Path icons | Out-Null }
# Copy the bundled backend binary into a sidecar path the Tauri shell will look up.
$sidecarSrc = Join-Path $OUT "pyi\dist\cheryy-server\cheryy-server.exe"
$sidecarDst = Join-Path $DESKTOP "src-tauri\cheryy-server.exe"
if (Test-Path $sidecarSrc) {
    Copy-Item -Force $sidecarSrc $sidecarDst
}
# Run Tauri via npx.cmd explicitly so `$LASTEXITCODE` reflects the underlying
# Tauri CLI exit code (which is what we want to fail on). On PowerShell 5.1 a
# naked `npx ...` would silently swallow a non-zero exit, which is why we
# validate here. Use the installed CLI if available; otherwise the npm-aliased
# version. Either way we assert the exit code.
$npxCmd = Get-Command npx.cmd -ErrorAction SilentlyContinue
if (-not $npxCmd) { $npxCmd = Get-Command npx -ErrorAction SilentlyContinue }
if (-not $npxCmd) {
    throw "npx was not found on PATH. Install Node.js >= 18 and ensure npm is on PATH."
}
Invoke-Step "Tauri build (npx @tauri-apps/cli@1.5 build)" {
    & $npxCmd.Source --yes @tauri-apps/cli@1.5 build
}
Pop-Location

# 5. Sanity-check that the installers actually exist so callers see a clear
#    message if the Tauri step exited 0 but produced nothing (rare).
$msiDir  = Join-Path $DESKTOP "src-tauri\target\release\bundle\msi"
$nsisDir = Join-Path $DESKTOP "src-tauri\target\release\bundle\nsis"
$msiCount  = if (Test-Path $msiDir)  { (Get-ChildItem $msiDir  -Filter '*.msi' -ErrorAction SilentlyContinue | Measure-Object).Count } else { 0 }
$nsisCount = if (Test-Path $nsisDir) { (Get-ChildItem $nsisDir -Filter '*.exe' -ErrorAction SilentlyContinue | Measure-Object).Count } else { 0 }
if ($msiCount -lt 1 -or $nsisCount -lt 1) {
    throw "Tauri build reported success but produced no installers (MSI=$msiCount, NSIS=$nsisCount). Inspect $DESKTOP\src-tauri\target\release\bundle\."
}

Write-Host "==> Done." -ForegroundColor Green
Write-Host "    Installer output: $DESKTOP\src-tauri\target\release\bundle\"
