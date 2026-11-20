# Builds app\hanami\ui\glasslens.dll, the suite's liquid glass drawn pixel by pixel, from
# glasslens.c with MSYS2's GCC (UCRT64, in Grabbit's build tools). The DLL is kept in git beside
# the source and copied to every app by tests\check_copies.py --sync, so an app's own build needs
# no compiler. Run again after changing glasslens.c.
$ErrorActionPreference = 'Stop'
$ui = Join-Path $PSScriptRoot '..\app\hanami\ui'
$bin = Join-Path $env:LOCALAPPDATA 'GrabbitBuild\msys64\ucrt64\bin'
if (-not (Test-Path (Join-Path $bin 'gcc.exe'))) { throw "No GCC at $bin (Grabbit's build\bootstrap.ps1 sets up MSYS2)." }
$env:PATH = "$bin;$env:PATH"
Push-Location $ui
try {
    & gcc -O3 -march=x86-64-v2 -ffast-math -shared -static-libgcc -s -o glasslens.dll glasslens.c glasslive.c -ldwmapi -lgdi32 -luser32
    if ($LASTEXITCODE -ne 0) { throw 'gcc failed' }
    & objdump -p glasslens.dll | Select-String 'DLL Name'
} finally {
    Pop-Location
}
