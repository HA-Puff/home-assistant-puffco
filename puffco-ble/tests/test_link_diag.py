"""Reconnect failure classification."""

import logging

from puffco_ble.constants import LoraxCharacteristics
from puffco_ble.link_diag import (
    CATEGORY_GATT_CACHE,
    CATEGORY_LORAX_NO_REPLY,
    CATEGORY_SMP_ABORT,
    classify_link_failure,
    log_link_diagnostic,
)


class _Char:
    def __init__(self, uuid: str) -> None:
        self.uuid = uuid


class _Service:
    def __init__(self, uuid: str, chars: list[str] | None = None) -> None:
        self.uuid = uuid
        self._chars = {char.lower(): _Char(char) for char in (chars or [])}

    def get_characteristic(self, uuid: str):
        found = self._chars.get(uuid.lower())
        if found is None:
            raise LookupError(uuid)
        return found


class _Services:
    def __init__(self, services: list[_Service]) -> None:
        self._services = services

    def __iter__(self):
        return iter(self._services)

    def get_service(self, uuid: str):
        for service in self._services:
            if service.uuid.lower() == uuid.lower():
                return service
        return None

    def get_characteristic(self, uuid: str):
        for service in self._services:
            found = service._chars.get(uuid.lower())
            if found is not None:
                return found
        raise LookupError(uuid)


class _Backend:
    def __init__(self, resolved: bool) -> None:
        self._properties = {"ServicesResolved": resolved}


class _Client:
    def __init__(
        self,
        *,
        connected: bool,
        services: _Services | None,
        resolved: bool | None = None,
        link_failure: dict[str, str] | None = None,
    ) -> None:
        self.is_connected = connected
        self._services = services
        self._backend = _Backend(resolved) if resolved is not None else None
        self.link_failure = link_failure

    @property
    def services(self):
        if self._services is None:
            raise RuntimeError("Service Discovery has not been performed yet")
        return self._services


_LORAX_CHARS = [
    LoraxCharacteristics.LORAX_VERSION,
    LoraxCharacteristics.LORAX_COMMAND,
    LoraxCharacteristics.LORAX_REPLY,
    LoraxCharacteristics.LORAX_EVENT,
]


def test_gatt_cache_when_services_resolved_without_lorax():
    assert (
        classify_link_failure(
            stage="gatt_discovery",
            connected=True,
            lorax_service_present=False,
            missing_chars=["service"],
            services_resolved=True,
            error_text="Lorax service missing from GATT discovery",
        )
        == CATEGORY_GATT_CACHE
    )


def test_gatt_cache_when_reply_characteristic_missing():
    assert (
        classify_link_failure(
            stage="notify",
            connected=True,
            lorax_service_present=True,
            missing_chars=["reply"],
            services_resolved=True,
            error_text="Characteristic reply was not found",
        )
        == CATEGORY_GATT_CACHE
    )


def test_lorax_no_reply_on_access_seed_timeout():
    assert (
        classify_link_failure(
            stage="get_access_seed",
            connected=True,
            lorax_service_present=True,
            missing_chars=[],
            services_resolved=True,
            error_text="GET_ACCESS_SEED timed out; GET_LIMITS also had no reply",
        )
        == CATEGORY_LORAX_NO_REPLY
    )


def test_seed_timeout_stays_lorax_even_if_snapshot_lost_the_service():
    assert (
        classify_link_failure(
            stage="get_access_seed",
            connected=False,
            lorax_service_present=False,
            missing_chars=["service"],
            services_resolved=None,
            error_text="GET_ACCESS_SEED timed out",
        )
        == CATEGORY_LORAX_NO_REPLY
    )


def test_smp_abort_on_authentication_canceled():
    assert (
        classify_link_failure(
            stage="pair",
            connected=False,
            lorax_service_present=False,
            missing_chars=["service"],
            services_resolved=False,
            error_text="org.bluez.Error.AuthenticationCanceled",
        )
        == CATEGORY_SMP_ABORT
    )


def test_smp_abort_when_link_drops_before_discovery():
    assert (
        classify_link_failure(
            stage="gatt_discovery",
            connected=False,
            lorax_service_present=False,
            missing_chars=["service"],
            services_resolved=False,
            error_text="Link already dropped before GATT discovery",
        )
        == CATEGORY_SMP_ABORT
    )


def test_log_line_includes_services_resolved_and_uuid(caplog):
    client = _Client(
        connected=True,
        resolved=True,
        services=_Services(
            [_Service("0000180a-0000-1000-8000-00805f9b34fb")]
        ),
    )
    with caplog.at_level(logging.WARNING, logger="puffco_ble.link_diag"):
        suffix = log_link_diagnostic(
            address="0C:43:14:B7:91:9C",
            heal="none",
            error=RuntimeError("Lorax service missing from GATT discovery"),
            client=client,
        )
    assert suffix == "category=gatt_cache_mismatch stage=gatt_discovery"
    text = caplog.text
    assert "link_diag category=gatt_cache_mismatch" in text
    assert "services_resolved=true" in text
    assert "lorax_service=missing" in text
    assert "0000180a-0000-1000-8000-00805f9b34fb" in text


def test_log_line_for_seed_timeout_uses_recorded_stage(caplog):
    client = _Client(
        connected=True,
        resolved=True,
        services=_Services(
            [_Service(LoraxCharacteristics.LORAX_SERVICE_UUID, _LORAX_CHARS)]
        ),
        link_failure={
            "stage": "get_access_seed",
            "detail": "GET_ACCESS_SEED timed out",
        },
    )
    with caplog.at_level(logging.WARNING, logger="puffco_ble.link_diag"):
        suffix = log_link_diagnostic(
            address="0C:43:14:B7:91:9C",
            heal="reconnect",
            error=RuntimeError("Lorax protocol initialization failed"),
            client=client,
        )
    assert suffix == "category=lorax_no_reply stage=get_access_seed"
    assert "missing=-" in caplog.text
    assert "heal=reconnect" in caplog.text


def test_scan_miss_is_not_a_link_diagnostic(caplog):
    with caplog.at_level(logging.WARNING, logger="puffco_ble.link_diag"):
        suffix = log_link_diagnostic(
            address="0C:43:14:B7:91:9C",
            heal="connect",
            error=RuntimeError("Device not visible during scan"),
            client=None,
        )
    assert suffix == ""
    assert caplog.text == ""
