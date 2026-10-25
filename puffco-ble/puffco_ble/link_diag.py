"""Classify a failed Peak reconnect into one observable layer.

The three categories are mutually exclusive so a later log review can tell a
stale GATT map from a silent Lorax handshake and from an SMP drop:

* ``gatt_cache_mismatch`` — the link is up (or BlueZ says services are
  resolved) and the Lorax service or its command/reply/event/version
  characteristics are absent.
* ``lorax_no_reply`` — those characteristics are present and
  ``GET_LIMITS`` / ``GET_ACCESS_SEED`` / ``UNLOCK`` gets no reply.
* ``smp_link_abort`` — the socket dies before that handshake, including
  ``AuthenticationCanceled`` and ``org.bluez.Error.Failed``.
"""

from __future__ import annotations

import logging
from typing import Any

from puffco_ble.constants import LoraxCharacteristics

_LOGGER = logging.getLogger(__name__)

CATEGORY_GATT_CACHE = "gatt_cache_mismatch"
CATEGORY_LORAX_NO_REPLY = "lorax_no_reply"
CATEGORY_SMP_ABORT = "smp_link_abort"

_LORAX_CHARS: tuple[tuple[str, str], ...] = (
    ("version", LoraxCharacteristics.LORAX_VERSION),
    ("command", LoraxCharacteristics.LORAX_COMMAND),
    ("reply", LoraxCharacteristics.LORAX_REPLY),
    ("event", LoraxCharacteristics.LORAX_EVENT),
)

_SMP_MARKERS = (
    "authenticationcanceled",
    "authentication cancelled",
    "authenticationfailed",
    "authentication failed",
    "org.bluez.error.failed",
    "org.bluez.error.authentication",
    "not connected during lorax",
    "link already dropped",
    "peak hung up",
    "gatt dropped",
    "did not stay connected",
    "did not reconnect",
    "connection aborted",
    "software caused connection abort",
)

_HANDSHAKE_STAGES = frozenset({"get_limits", "get_access_seed", "unlock"})
_NO_REPLY_MARKERS = ("timed out", "no reply", "replies not received")
_SKIP_MARKERS = ("not visible",)


def _services_resolved(client: Any) -> bool | None:
    """Read BlueZ ``ServicesResolved`` when the Bleak backend exposes it."""
    seen: set[int] = set()
    stack: list[tuple[Any, int]] = [(client, 0)]
    while stack:
        obj, depth = stack.pop()
        if obj is None or depth > 4:
            continue
        ident = id(obj)
        if ident in seen:
            continue
        seen.add(ident)
        props = getattr(obj, "_properties", None)
        if isinstance(props, dict) and "ServicesResolved" in props:
            return bool(props["ServicesResolved"])
        if depth == 4:
            continue
        for name in ("_backend", "_client", "_device", "device"):
            child = getattr(obj, name, None)
            if child is not None and child is not obj:
                stack.append((child, depth + 1))
    return None


def snapshot_gatt(client: Any | None) -> dict[str, Any]:
    """Public GATT facts available without another round-trip to the Peak."""
    if client is None:
        return {
            "connected": False,
            "services_resolved": None,
            "lorax_service_present": False,
            "missing": ["service"],
            "service_uuids": [],
            "services_error": "no client",
        }

    connected = bool(getattr(client, "is_connected", False))
    services_resolved = _services_resolved(client)
    service_uuids: list[str] = []
    missing: list[str] = []
    lorax_present = False
    services_error = ""
    try:
        services = client.services
    except Exception as err:  # noqa: BLE001 — discovery errors are the signal
        services = None
        services_error = str(err)

    if services is not None:
        try:
            service_uuids = [str(service.uuid).lower() for service in services]
        except Exception as err:  # noqa: BLE001
            services_error = services_error or str(err)
        try:
            lorax_present = (
                services.get_service(LoraxCharacteristics.LORAX_SERVICE_UUID) is not None
            )
        except Exception as err:  # noqa: BLE001
            services_error = services_error or str(err)
            lorax_present = False
        if lorax_present:
            for name, uuid in _LORAX_CHARS:
                try:
                    found = services.get_characteristic(uuid) is not None
                except Exception:  # noqa: BLE001
                    found = False
                if not found:
                    missing.append(name)
        else:
            missing.append("service")
    else:
        missing.append("service")

    return {
        "connected": connected,
        "services_resolved": services_resolved,
        "lorax_service_present": lorax_present,
        "missing": missing,
        "service_uuids": service_uuids,
        "services_error": services_error,
    }


def classify_link_failure(
    *,
    stage: str,
    connected: bool,
    lorax_service_present: bool,
    missing_chars: list[str],
    services_resolved: bool | None,
    error_text: str,
) -> str:
    """Map one failed attempt onto ``gatt_cache_mismatch``, ``lorax_no_reply``, or ``smp_link_abort``."""
    text = (error_text or "").lower()
    if any(marker in text for marker in _SMP_MARKERS):
        return CATEGORY_SMP_ABORT

    # Handshake stages are recorded only after the Lorax service was usable.
    # A later snapshot can lose that service if the link drops during the wait.
    if stage in _HANDSHAKE_STAGES or any(marker in text for marker in _NO_REPLY_MARKERS):
        return CATEGORY_LORAX_NO_REPLY

    if stage in ("connect", "pair", "version", "notify", "gatt_discovery") and not connected:
        return CATEGORY_SMP_ABORT

    service_missing = not lorax_service_present
    chars_missing = any(name != "service" for name in missing_chars)
    resolved_or_up = connected or services_resolved is True
    if resolved_or_up and (service_missing or chars_missing):
        return CATEGORY_GATT_CACHE

    if not connected:
        return CATEGORY_SMP_ABORT
    if service_missing or chars_missing:
        return CATEGORY_GATT_CACHE
    return CATEGORY_LORAX_NO_REPLY


def _stage_from_error(error_text: str) -> str:
    text = error_text.lower()
    if "get_access_seed" in text or "access_seed" in text:
        return "get_access_seed"
    if "unlock" in text:
        return "unlock"
    if "get_limits" in text or "limits" in text:
        return "get_limits"
    if "lorax service missing" in text or "service discovery" in text or "gatt discovery" in text:
        return "gatt_discovery"
    if "link already dropped" in text or "hung up" in text:
        return "gatt_discovery"
    if "notification" in text:
        return "notify"
    if "version" in text:
        return "version"
    if "pair" in text or "authentication" in text:
        return "pair"
    return "connect"


def log_link_diagnostic(
    *,
    address: str,
    heal: str,
    error: BaseException | str,
    client: Any | None = None,
) -> str:
    """Emit one ``link_diag`` warning and return ``category=... stage=...``.

    Scan misses are not a degraded link, so they are not logged.
    """
    error_text = str(error)
    if any(marker in error_text.lower() for marker in _SKIP_MARKERS):
        return ""

    failure = getattr(client, "link_failure", None) if client is not None else None
    if isinstance(failure, dict) and failure.get("detail"):
        detail = str(failure["detail"])
        stage = str(failure.get("stage") or _stage_from_error(detail))
    else:
        detail = error_text
        stage = _stage_from_error(error_text)

    snap = snapshot_gatt(client)
    if snap["services_error"] and snap["services_error"] not in detail:
        detail = f"{detail}; services: {snap['services_error']}"

    category = classify_link_failure(
        stage=stage,
        connected=bool(snap["connected"]),
        lorax_service_present=bool(snap["lorax_service_present"]),
        missing_chars=list(snap["missing"]),
        services_resolved=snap["services_resolved"],
        error_text=detail,
    )
    resolved = snap["services_resolved"]
    resolved_text = "unknown" if resolved is None else str(resolved).lower()
    missing = ",".join(snap["missing"]) or "-"
    services = ",".join(snap["service_uuids"][:12]) or "-"
    _LOGGER.warning(
        "link_diag category=%s address=%s stage=%s heal=%s connected=%s "
        "services_resolved=%s lorax_service=%s missing=%s services=%s error=%s",
        category,
        address,
        stage,
        heal,
        "yes" if snap["connected"] else "no",
        resolved_text,
        "present" if snap["lorax_service_present"] else "missing",
        missing,
        services,
        detail,
    )
    return f"category={category} stage={stage}"
