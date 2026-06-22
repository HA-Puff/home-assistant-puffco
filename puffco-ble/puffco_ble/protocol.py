"""Protocol detection and device discovery."""

from __future__ import annotations

import re

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from puffco_ble.constants import (
    LORAX_SERVICE_UUID,
    PEAK_PRO_MAC_PREFIXES,
    SERVICE_UUID,
)

# Names seen in the wild (custom device name, default, pairing mode)
PUFFCO_NAME_HINTS = (
    "puffco",
    "peak",
    "peak pro",
    "proxy",
)


def is_peak_pro_advertisement(
    device: BLEDevice, advertisement: AdvertisementData
) -> bool:
    if any(device.address.upper().startswith(p.upper()) for p in PEAK_PRO_MAC_PREFIXES):
        return True
    uuids = {u.lower() for u in advertisement.service_uuids}
    if SERVICE_UUID.lower() in uuids or LORAX_SERVICE_UUID.lower() in uuids:
        return True
    name = (device.name or advertisement.local_name or "").lower()
    if any(hint in name for hint in PUFFCO_NAME_HINTS):
        return True
    # Default Puffco BLE name is often the MAC with colons removed (12 hex chars)
    if name and re.fullmatch(r"[0-9a-f]{12}", name):
        return True
    return False


async def scan_ble_devices(
    timeout: float = 10.0,
) -> list[tuple[BLEDevice, AdvertisementData]]:
    """Return all BLE devices seen during scan."""
    discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    return list(discovered.values())


async def find_device_by_address(
    address: str, timeout: float = 15.0
) -> BLEDevice | None:
    """Scan for a specific MAC — required for reliable connect on Windows."""
    import logging

    log = logging.getLogger(__name__)
    normalized = address.upper()
    log.debug("find_device_by_address(%s, timeout=%s)", normalized, timeout)
    device = await BleakScanner.find_device_by_address(normalized, timeout=timeout)
    if device is not None:
        log.info("Located %s via targeted scan", normalized)
        return device
    log.debug("Targeted scan missed %s, trying full scan...", normalized)
    # Fallback: full scan (sometimes returns richer device objects on WinRT)
    for dev, _adv in await scan_ble_devices(timeout=min(timeout, 10.0)):
        if dev.address.upper() == normalized:
            log.info("Located %s via full BLE scan", normalized)
            return dev
    log.warning(
        "Device %s not seen during %.0fs scan — re-enter pairing mode (blue bar) and retry",
        normalized,
        timeout,
    )
    return None


async def scan_peak_pro_devices(
    timeout: float = 10.0,
) -> list[tuple[BLEDevice, AdvertisementData]]:
    results: list[tuple[BLEDevice, AdvertisementData]] = []
    for device, adv in await scan_ble_devices(timeout=timeout):
        if is_peak_pro_advertisement(device, adv):
            results.append((device, adv))
    return results
