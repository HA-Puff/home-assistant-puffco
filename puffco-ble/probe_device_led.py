"""READ-ONLY device probe: determine LED API version + capture raw LED blobs.

No writes are performed. Reads:
  /p/sys/fw/api    - numeric API version (uint32)
  /u/app/hc/0/phcl - heatCycle0PreheatColor (ENOENT => LED API V3)
  /p/app/ltrn/colr - lantern color / CompiledMoodLight (raw)
  /p/app/ltrn/scpd - lantern scratchpad (raw)
  /p/app/led/aclr  - active LED color (raw)
  /u/app/led/ca/5  - lantern userColorArray (default index 5)
  /u/app/led/oa/5  - lantern userOffsetArray
"""

from __future__ import annotations

import asyncio
import logging
import os

from puffco_ble.client import PuffcoClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_LOG = logging.getLogger("probe")

MAC = os.environ.get("PUFFCO_MAC", "0C:43:14:B7:91:9C")

PATHS = [
    "/p/sys/fw/api",
    "/u/app/hc/0/phcl",
    "/p/app/ltrn/colr",
    "/p/app/ltrn/scpd",
    "/p/app/led/aclr",
    "/u/app/led/ca/5",
    "/u/app/led/oa/5",
    "/u/app/led/aa/5",
]


async def main() -> None:
    async with PuffcoClient(MAC) as client:
        bleak = client.bleak
        for path in PATHS:
            try:
                v = await bleak.lorax_read_short(path)
                _LOG.info("READ %-18s len=%3s  hex=%s", path, len(v), v.hex())
            except Exception as err:  # noqa: BLE001
                _LOG.info("READ %-18s -> ERROR: %s", path, err)


if __name__ == "__main__":
    asyncio.run(main())
