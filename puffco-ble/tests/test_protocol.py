"""Protocol detection tests."""

from types import SimpleNamespace

from puffco_ble.constants import (
    LORAX_SERVICE_UUID,
    PUFFCO_MANUFACTURER_ID,
    SERVICE_UUID,
)
from puffco_ble.protocol import is_peak_pro_advertisement


def _device(address: str, name: str = "") -> SimpleNamespace:
    return SimpleNamespace(address=address, name=name)


def _adv(**kwargs: object) -> SimpleNamespace:
    data = {
        "service_uuids": [],
        "manufacturer_data": {},
        "local_name": "",
    }
    data.update(kwargs)
    return SimpleNamespace(**data)


def test_detect_by_service_uuid():
    assert is_peak_pro_advertisement(
        _device("11:22:33:44:55:66"), _adv(service_uuids=[SERVICE_UUID])
    )


def test_detect_by_lorax_uuid():
    assert is_peak_pro_advertisement(
        _device("11:22:33:44:55:66"), _adv(service_uuids=[LORAX_SERVICE_UUID])
    )


def test_detect_by_mac_prefix():
    assert is_peak_pro_advertisement(_device("84:2E:14:AA:BB:CC"), _adv())


def test_detect_by_manufacturer_data():
    assert is_peak_pro_advertisement(
        _device("11:22:33:44:55:66"),
        _adv(manufacturer_data={PUFFCO_MANUFACTURER_ID: b"\x01"}),
    )


def test_reject_unrelated_device():
    assert not is_peak_pro_advertisement(
        _device("11:22:33:44:55:66", name="kitchen sensor"),
        _adv(service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"]),
    )
