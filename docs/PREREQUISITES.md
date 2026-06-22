# Puffco Integration — Prerequisites

Complete this checklist before running hardware validation or deploying to Home Assistant.

## Device information

| Field | Your value | Notes |
|-------|------------|-------|
| Device model | _fill in_ | Peak Pro, 3DXL, Proxy, etc. |
| Bluetooth MAC | _fill in_ | Settings → Bluetooth on phone, or scan with `puffco-cli scan` |
| Firmware revision | AW (expected) | Shown in official app or `puffco-cli info` |
| Protocol | Lorax (expected for FW AW) | Auto-detected on connect |

## Development machine

- Python 3.10+
- Bluetooth 4.0+ adapter (built-in or USB dongle)
- Close the official Puffco Connect app while testing (only one BLE master at a time)
- Put device in pairing mode: hold power until light bar glows blue

### Windows setup

```powershell
git clone https://github.com/HA-Puff/home-assistant-puffco.git
cd puffco-home-assistant
python -m venv .venv
.venv\Scripts\activate
pip install -e "./puffco-ble[dev]"
```

### Linux setup (matches Home Assistant host)

```bash
sudo apt install bluez python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -e "./puffco-ble[dev]"
```

## Home Assistant host

| HA install type | Bluetooth requirement |
|-----------------|----------------------|
| HA OS (Pi, NUC) | Built-in or USB dongle; verify under Settings → System → Hardware |
| Docker | `--privileged` + pass USB device (`/dev/bus/usb` or `/dev/ttyUSB0`) |
| Supervised | `bluetooth` integration enabled; adapter not used by host OS |

Copy `custom_components/puffco/` to your HA config directory (see [DEPLOY.md](DEPLOY.md)).

## Environment variables (optional)

```bash
export PUFFCO_MAC="AA:BB:CC:DD:EE:FF"   # default for CLI when --mac omitted
export PUFFCO_LOG_DIR="./logs"          # raw BLE trace output
```
