#!/usr/bin/env bash
# Sync puffco_ble library into the vendored HA copy (excludes CLI).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
rsync -a --delete --exclude='cli.py' \
  "$ROOT/puffco-ble/puffco_ble/" \
  "$ROOT/custom_components/puffco/_vendor/puffco_ble/"
echo "Synced puffco_ble -> custom_components/puffco/_vendor/puffco_ble"
