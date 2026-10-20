# Hanami build bootstrap - fetches everything needed to run and build Hanami.
#
#   powershell -ExecutionPolicy Bypass -File build\bootstrap.ps1
#
# Everything heavy lives in %LOCALAPPDATA%\HanamiBuild so the project folder
# stays small. Delete that folder any time; this script recreates it.
#   venv\   Python venv with PySide6 and PyInstaller
# The script is idempotent: finished steps are skipped on re-run.

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$Cache = Join-Path $env:LOCALAPPDATA 'HanamiBuild'
$Venv  = Join-Path $Cache 'venv'
New-Item -ItemType Directory -Force $Cache | Out-Null

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

$py = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "venv    $Venv"
    & py -3.12 -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'venv creation failed (needs Python 3.12 via the py launcher)' }
}
& $py -m pip install --disable-pip-version-check --upgrade pip | Out-Null
& $py -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'pip install failed' }
Write-Host 'Python venv ready'
