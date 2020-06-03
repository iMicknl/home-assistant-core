"""The Tahoma integration."""
import asyncio

import voluptuous as vol
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, ATTR_RSSI_LEVEL, TAHOMA_TYPES, CORE_RSSI_LEVEL_STATE
from .tahoma_api import TahomaApi, Action
from requests.exceptions import RequestException

from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    discovery,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

PLATFORMS = ["light", "cover", "sensor", "lock"]


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Tahoma component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Tahoma from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]

    try:
        controller = TahomaApi(username, password)
        controller.get_setup()
        devices = controller.get_devices()
        # scenes = api.get_action_groups()

    except RequestException:
        _LOGGER.exception("Error when getting devices from the Tahoma API")
        return False

    hass.data[DOMAIN][entry.entry_id] = {"controller": controller, "devices": []}

    # List devices
    for device in devices:
        _device = controller.get_device(device)

        if _device.uiclass in TAHOMA_TYPES:
            if TAHOMA_TYPES[_device.uiclass] in PLATFORMS:
                component = TAHOMA_TYPES[_device.uiclass]

                hass.data[DOMAIN][entry.entry_id]["devices"].append(_device)

                hass.async_create_task(
                    hass.config_entries.async_forward_entry_setup(entry, component)
                )
        else:
            _LOGGER.warning(
                "Unsupported Tahoma device (%s - %s - %s) ",
                _device.type,
                _device.uiclass,
                _device.widget,
            )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN][entry.entry_id].pop(entry.entry_id)

    return unload_ok


class TahomaDevice(Entity):
    """Representation of a Tahoma device entity."""

    def __init__(self, tahoma_device, controller):
        """Initialize the device."""
        self.tahoma_device = tahoma_device
        self._name = self.tahoma_device.label
        self.controller = controller

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def unique_id(self) -> str:
        return self.tahoma_device.url

    @property
    def device_state_attributes(self):
        """Return the state attributes of the device."""

        attr = {
            "uiclass": self.tahoma_device.uiclass,
            "widget": self.tahoma_device.widget,
            "type": self.tahoma_device.type,
        }

        if CORE_RSSI_LEVEL_STATE in self.tahoma_device.active_states:
            attr[ATTR_RSSI_LEVEL] = self.tahoma_device.active_states[
                CORE_RSSI_LEVEL_STATE
            ]

        return attr

    @property
    def device_info(self):
        """Return device registry information for this entity."""
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "manufacturer": "Somfy",
            "name": self.name,
            "model": self.tahoma_device.widget
        }

    def apply_action(self, cmd_name, *args):
        """Apply Action to Device."""

        action = Action(self.tahoma_device.url)
        action.add_command(cmd_name, *args)
        self.controller.apply_actions("HomeAssistant", [action])
