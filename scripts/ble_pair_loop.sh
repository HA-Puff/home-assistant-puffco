#!/bin/sh
# Repeatedly attempt a BlueZ bond with the Peak Pro so one attempt lands inside
# the device's short pairing (BONDING) window. Run on the Home Assistant host.
MAC="${1:-0C:43:14:B7:91:9C}"

for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  echo "--- try $i at $(date +%H:%M:%S) ---"
  {
    printf 'agent NoInputNoOutput\n'
    sleep 1
    printf 'default-agent\n'
    sleep 1
    printf 'pair %s\n' "$MAC"
    sleep 15
  } | timeout 20 bluetoothctl 2>&1 \
      | sed -e 's/\x1b\[[0-9;]*m//g' \
      | grep -aE 'Pairing successful|Failed to pair|Attempting to pair'

  if bluetoothctl devices Paired 2>/dev/null | grep -qi "$MAC"; then
    echo "BONDED_OK on try $i"
    break
  fi
done

echo "=== FINAL STATE ==="
{ printf 'info %s\n' "$MAC"; sleep 4; } | timeout 10 bluetoothctl 2>&1 \
  | sed -e 's/\x1b\[[0-9;]*m//g' \
  | grep -aE 'Paired:|Bonded:|Connected:'
echo DONE_LOOP
