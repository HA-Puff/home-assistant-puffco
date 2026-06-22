# Sync puffco_ble library into Home Assistant custom component
$Source = Join-Path $PSScriptRoot "..\puffco-ble\puffco_ble"
$Dest = Join-Path $PSScriptRoot "..\custom_components\puffco\puffco_ble"
robocopy $Source $Dest /E /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { exit 1 }
Write-Host "Synced puffco_ble -> custom_components/puffco/puffco_ble"
