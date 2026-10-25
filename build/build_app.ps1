# Packages Hanami into dist\Hanami\Hanami.exe.
#
#   powershell -ExecutionPolicy Bypass -File build\build_app.ps1
#
# Needs bootstrap.ps1 (venv).

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$Root  = Split-Path -Parent $PSScriptRoot
$Cache = Join-Path $env:LOCALAPPDATA 'HanamiBuild'
$Py    = Join-Path $Cache 'venv\Scripts\python.exe'
$Dist  = Join-Path $Root 'dist\Hanami'

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path $Py)) { Fail "venv missing - run build\bootstrap.ps1 first" }
# PyInstaller empties dist\Hanami first and stops at the first file in use,
# which leaves a running copy with half its files gone.
$Running = Get-Process -Name Hanami -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -and $_.Path -like (Join-Path $Dist '*') }
if ($Running) { Fail "Hanami is running from $Dist - quit it from the tray first" }

# Every module must at least import before it is packaged: a mistake caught
# here prints a traceback, where the windowed exe would put up an error box.
Write-Host '>> import check'
& $Py -c "import sys; sys.path.insert(0, r'$Root\app'); import hanami.app"
if ($LASTEXITCODE -ne 0) { Fail 'Hanami does not import - fix the error above' }

Write-Host '>> icon'
& $Py (Join-Path $PSScriptRoot 'make_icon.py')
if ($LASTEXITCODE -ne 0) { Fail 'icon generation failed' }

Write-Host '>> PyInstaller'
Push-Location $Root
& $Py -m PyInstaller --noconfirm --clean --distpath (Join-Path $Root 'dist') `
    --workpath (Join-Path $Cache 'pyinstaller') (Join-Path $PSScriptRoot 'hanami.spec')
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Fail "PyInstaller failed ($code)" }
if (-not (Test-Path (Join-Path $Dist 'Hanami.exe'))) { Fail 'Hanami.exe was not produced' }
Copy-Item (Join-Path $Root 'README.md') $Dist -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root 'THIRD-PARTY-NOTICES.md') $Dist -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root 'LICENSE') $Dist -Force -ErrorAction SilentlyContinue

# Hanami Sensors - the processor's temperature - goes beside it: the service and its setup.
Write-Host '>> Hanami Sensors'
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root 'sensors\build.ps1') -Out (Join-Path $Dist 'sensors')
if ($LASTEXITCODE -ne 0) { Fail 'Hanami Sensors did not build' }

# Does it start? --self-test loads what a real start loads and answers with
# the version, without showing anything.
$Answer = Join-Path $env:TEMP "hanami-build-self-test-$PID.txt"
Remove-Item $Answer -ErrorAction SilentlyContinue
$Probe = Start-Process -FilePath (Join-Path $Dist 'Hanami.exe') -ArgumentList '--self-test', "`"$Answer`"" -PassThru
if (-not $Probe.WaitForExit(120000)) { $Probe.Kill(); Fail 'the built Hanami.exe hung when started (--self-test)' }
$Said = if (Test-Path $Answer) { (Get-Content -Raw $Answer).Trim() } else { '' }
Remove-Item $Answer -ErrorAction SilentlyContinue
if (-not $Said) { Fail 'the built Hanami.exe does not start (--self-test gave no answer)' }
if ($Said.StartsWith('FAILED')) { Fail "the built Hanami.exe starts but its self-test failed: $Said" }
Write-Host ">> it starts: Hanami $Said"

$size = (Get-ChildItem $Dist -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ('>> done: {0}  ({1:N0} MB)' -f (Join-Path $Dist 'Hanami.exe'), ($size / 1MB))
