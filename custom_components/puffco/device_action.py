"""Device automation actions for Puffco."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType, TemplateVarsType

from .const import DOMAIN
from .helpers import get_coordinator_for_device

ACTION_TYPES = {"start_session", "abort_session", "reconnect", "set_profile"}

ACTION_SCHEMA = cv.DEVICE_ACTION_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_TYPE): vol.In(ACTION_TYPES),
        vol.Optional("profile"): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
        vol.Optional("clear_bond", default=False): cv.boolean,
    }
)


async def async_get_actions(
    hass: HomeAssistant, device_id: str
) -> list[dict]:
    device = dr.async_get(hass).async_get(device_id)
    if device is None or not any(
        identifier[0] == DOMAIN for identifier in device.identifiers
    ):
        return []
    actions = [
        {
            CONF_DOMAIN: DOMAIN,
            CONF_TYPE: "start_session",
            CONF_DEVICE_ID: device_id,
        },
        {
            CONF_DOMAIN: DOMAIN,
            CONF_TYPE: "abort_session",
            CONF_DEVICE_ID: device_id,
        },
        {
            CONF_DOMAIN: DOMAIN,
            CONF_TYPE: "reconnect",
            CONF_DEVICE_ID: device_id,
        },
    ]
    for profile in range(1, 5):
        actions.append(
            {
                CONF_DOMAIN: DOMAIN,
                CONF_TYPE: "set_profile",
                CONF_DEVICE_ID: device_id,
                "profile": profile,
            }
        )
    return actions


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: ConfigType,
    variables: TemplateVarsType,
    context: Context | None,
) -> None:
    coordinator, _entry_id = get_coordinator_for_device(hass, config[CONF_DEVICE_ID])
    if coordinator is None:
        return
    action_type = config[CONF_TYPE]
    if action_type == "start_session":
        await coordinator.async_start_session(config.get("profile"))
    elif action_type == "abort_session":
        await coordinator.async_abort_session()
    elif action_type == "reconnect":
        await coordinator.async_reconnect(clear_bond=config.get("clear_bond", False))
    elif action_type == "set_profile" and "profile" in config:
        await coordinator.async_set_profile(config["profile"])
