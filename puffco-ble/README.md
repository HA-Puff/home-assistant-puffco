# puffco-ble

Standalone Python library for Puffco Peak Pro Bluetooth control. Supports Flat GATT (Firmware W/X) and Lorax path-based protocol (Firmware AG+).

Adapted from [PuffcoPC](https://github.com/meekzyr/PuffcoPC) and the [Puffco reverse-engineering writeup](../Existing-Integration/Puffco-Reverse-Engineering-Writeup-main/README.md).

## Install

```bash
pip install -e ".[dev]"
```

## CLI

```bash
puffco-cli scan
puffco-cli --mac AA:BB:CC:DD:EE:FF info
puffco-cli --mac AA:BB:CC:DD:EE:FF read dabs
puffco-cli --mac AA:BB:CC:DD:EE:FF set-temp --profile 1 --celsius 260
puffco-cli --mac AA:BB:CC:DD:EE:FF start
puffco-cli --mac AA:BB:CC:DD:EE:FF color --rgb FF0000
```

## Library usage

```python
import asyncio
from puffco_ble import PuffcoClient

async def main():
    async with PuffcoClient("AA:BB:CC:DD:EE:FF") as client:
        data = await client.fetch_data()
        print(data.total_dabs, data.heater_temp_c)

asyncio.run(main())
```
