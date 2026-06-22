"""Protocol detection tests."""

from unittest.mock import MagicMock

from puffco_ble.constants import LORAX_SERVICE_UUID, SERVICE_UUID
from puffco_ble.protocol import is_peak_pro_advertisement


def test_detect_by_service_uuid():
    device = MagicMock(address="11:22:33:44:55:66")
    adv = MagicMock(service_uuids=[SERVICE_UUID])
    assert is_peak_pro_advertisement(device, adv) is True


def test_detect_by_lorax_uuid():
    device = MagicMock(address="11:22:33:44:55:66")
    adv = MagicMock(service_uuids=[LORAX_SERVICE_UUID])
    assert is_peak_pro_advertisement(device, adv) is True


def test_detect_by_mac_prefix():
    device = MagicMock(address="84:2E:14:AA:BB:CC")
    adv = MagicMock(service_uuids=[])
    assert is_peak_pro_advertisement(device, adv) is True


def test_reject_unrelated_device():
    device = MagicMock(address="11:22:33:44:55:66")
    adv = MagicMock(service_uuids=["0000180f-0000-1000-8000-00805f9b34fb"])
    assert is_peak_pro_advertisement(device, adv) is False
