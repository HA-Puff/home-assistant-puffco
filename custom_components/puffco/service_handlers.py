"""Domain services for Puffco."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .helpers import get_coordinator_from_service_call

SERVICE_START_SESSION = "start_session"
SERVICE_ABORT_SESSION = "abort_session"
SERVICE_SET_PROFILE = "set_profile"
SERVICE_RECONNECT = "reconnect"

SERVICE_START_SESSION_SCHEMA = cv.make_entity_service_schema(
    {vol.Optional("profile"): vol.All(vol.Coerce(int), vol.Range(min=1, max=4))}
)

SERVICE_SET_PROFILE_SCHEMA = cv.make_entity_service_schema(
    {vol.Required("profile"): vol.All(vol.Coerce(int), vol.Range(min=1, max=4))}
)

SERVICE_RECONNECT_SCHEMA = cv.make_entity_service_schema(
    {vol.Optional("clear_bond", default=False): cv.boolean}
)


async def _async_get_coordinator(call: ServiceCall):
    coordinator, _entry_id = get_coordinator_from_service_call(call.hass, call)
    if coordinator is None:
        raise ServiceValidationError(
            "No Puffco device found for this service call target"
        )
    return coordinator


async def async_start_session(call: ServiceCall) -> None:
    coordinator = await _async_get_coordinator(call)
    await coordinator.async_start_session(call.data.get("profile"))


async def async_abort_session(call: ServiceCall) -> None:
    coordinator = await _async_get_coordinator(call)
    await coordinator.async_abort_session()


async def async_set_profile(call: ServiceCall) -> None:
    coordinator = await _async_get_coordinator(call)
    await coordinator.async_set_profile(call.data["profile"])


async def async_reconnect(call: ServiceCall) -> None:
    coordinator = await _async_get_coordinator(call)
    try:
        await coordinator.async_reconnect(clear_bond=call.data.get("clear_bond", False))
    except HomeAssistantError:
        raise


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_START_SESSION):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_START_SESSION,
        async_start_session,
        schema=SERVICE_START_SESSION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ABORT_SESSION,
        async_abort_session,
        schema=cv.make_entity_service_schema({}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PROFILE,
        async_set_profile,
        schema=SERVICE_SET_PROFILE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RECONNECT,
        async_reconnect,
        schema=SERVICE_RECONNECT_SCHEMA,
    )
