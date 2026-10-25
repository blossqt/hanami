# Builds Hanami Sensors - the service and its setup - into a folder: dist\Hanami\sensors, when
# build_app.ps1 runs it. Needs the .NET 10 SDK.
#
#   powershell -ExecutionPolicy Bypass -File sensors\build.ps1 -Out <folder>
#
# The service is published first; then each of its files' SHA-256 goes into the setup's source
# (setup\FileHashes.g.cs, not in git), so the setup installs nothing that changed since; then the
# setup is built, and asked to check the service's files as they now lie beside it.

param([Parameter(Mandatory = $true)][string]$Out)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Here = $PSScriptRoot
$Work = Join-Path $env:LOCALAPPDATA 'HanamiBuild\sensors'
$Service = Join-Path $Work 'service'
$Setup = Join-Path $Work 'setup'

function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) { Fail 'the .NET 10 SDK (dotnet) is missing' }
foreach ($dir in $Service, $Setup) { if (Test-Path $dir) { Remove-Item $dir -Recurse -Force } }

& dotnet publish (Join-Path $Here 'service\HanamiSensors.csproj') -c Release -o $Service --nologo -v quiet
if ($LASTEXITCODE -ne 0) { Fail 'the service did not build' }

$base = (Get-Item $Service).FullName.TrimEnd('\')
$entries = Get-ChildItem $base -Recurse -File | Sort-Object FullName | ForEach-Object {
    $name = $_.FullName.Substring($base.Length + 1)
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    "        (@`"$name`", `"$hash`"),"
}
if (-not $entries) { Fail 'the service was published empty' }
$code = @(
    '// Made by sensors\build.ps1 from the published service: each of its files and its SHA-256. Not in git.'
    'namespace HanamiSensorsSetup;'
    ''
    'static class FileHashes'
    '{'
    '    public static readonly (string Name, string Sha256)[] Files ='
    '    ['
) + $entries + @(
    '    ];'
    '}'
)
Set-Content -Path (Join-Path $Here 'setup\FileHashes.g.cs') -Value $code -Encoding utf8

& dotnet publish (Join-Path $Here 'setup\HanamiSensorsSetup.csproj') -c Release -o $Setup --nologo -v quiet
if ($LASTEXITCODE -ne 0) { Fail 'the setup did not build' }

if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }
New-Item -ItemType Directory $Out | Out-Null
Copy-Item (Join-Path $Setup '*') $Out -Recurse
Copy-Item $Service (Join-Path $Out 'service') -Recurse

$check = Start-Process -FilePath (Join-Path $Out 'HanamiSensorsSetup.exe') -ArgumentList '--verify' -Wait -PassThru -NoNewWindow
if ($check.ExitCode -ne 0) { Fail "the setup does not accept the service's files (exit $($check.ExitCode))" }
Write-Host (">> Hanami Sensors {0}: {1} files checked, in {2}" -f `
    (Get-Item (Join-Path $Out 'service\HanamiSensors.exe')).VersionInfo.FileVersion, $entries.Count, $Out)
