# Hardware validation checklist

Run with the Puffco in pairing mode and the official app closed.

```powershell
cd puffco-ble
.venv\Scripts\activate
$env:PUFFCO_MAC = "AA:BB:CC:DD:EE:FF"  # your MAC
```

| Step | Command | Expected |
|------|---------|----------|
| 1 | `puffco-cli scan` | Device listed with service UUID |
| 2 | Remove from **Windows Bluetooth** if listed (do not pair via Settings) |
| 3 | `puffco-cli -v info` | Firmware revision, protocol `lorax` or `flat` |
| 3 | `puffco-cli auth-test` | PASS |
| 4 | `puffco-cli read dabs` | Integer total_dabs |
| 5 | Manual dab on device, re-run read dabs | Count incremented |
| 6 | `puffco-cli set-temp --profile 1 --celsius 260` | Read-back within 1°C |
| 7 | `puffco-cli start` | operating_state preheat/active |
| 8 | `puffco-cli color --rgb FF0000 --lantern-on` | Red lantern visible |
| 9 | `puffco-cli lantern off` | Lantern off |

Raw logs are written to `logs/` when commands succeed.

If Lorax auth fails on recent firmware, enable debug logging (`-v`) and compare opcode errors against the official app’s Lorax authenticate path.
