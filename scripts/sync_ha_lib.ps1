# Sync puffco_ble library into the vendored HA copy (excludes CLI).
$Source = Join-Path $PSScriptRoot "..\puffco-ble\puffco_ble"
$Dest = Join-Path $PSScriptRoot "..\custom_components\puffco\_vendor\puffco_ble"
robocopy $Source $Dest /E /XF cli.py /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { exit 1 }
Write-Host "Synced puffco_ble -> custom_components/puffco/_vendor/puffco_ble"
