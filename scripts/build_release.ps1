# Build a HACS/manual install zip (integration folder only).
param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Dist = Join-Path $Root "dist"
$Stage = Join-Path $Dist "stage"
$Target = Join-Path $Stage "custom_components\puffco"
$Zip = Join-Path $Dist "puffco-home-assistant-$Version.zip"

$Source = Join-Path $Root "custom_components\puffco"
if (-not (Test-Path $Source)) {
    throw "Missing $Source"
}

if (Test-Path $Stage) { Remove-Item -Recurse -Force $Stage }
New-Item -ItemType Directory -Path $Target -Force | Out-Null

# Copy integration (exclude __pycache__)
robocopy $Source $Target /E /XD __pycache__ .pytest_cache /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit $LASTEXITCODE" }

if (-not (Test-Path $Dist)) { New-Item -ItemType Directory -Path $Dist | Out-Null }
if (Test-Path $Zip) { Remove-Item -Force $Zip }

Compress-Archive -Path (Join-Path $Stage "custom_components") -DestinationPath $Zip -Force
Remove-Item -Recurse -Force $Stage

Write-Host "Created $Zip"
Get-Item $Zip | Format-List Name, Length, LastWriteTime
