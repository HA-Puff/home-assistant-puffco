#!/usr/bin/env bash
# Sync puffco_ble library into Home Assistant custom component
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
robocopy() { rsync -a --delete "$@"; }
rsync -a --delete "$ROOT/puffco-ble/puffco_ble/" "$ROOT/custom_components/puffco/puffco_ble/"
echo "Synced puffco_ble -> custom_components/puffco/puffco_ble"
