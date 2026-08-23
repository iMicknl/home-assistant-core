"""Provides diagnostics for Overkiz."""

from typing import TYPE_CHECKING, Any

from pyoverkiz.enums import APIType
from pyoverkiz.models import DeviceIdentifier
from pyoverkiz.obfuscate import obfuscate_id

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import OverkizDataConfigEntry
from .const import CONF_API_TYPE, CONF_HUB, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OverkizDataConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    client = entry.runtime_data.coordinator.client

    data = {
        **await client.get_diagnostic_data(),
        "server": entry.data[CONF_HUB],
        "api_type": entry.data.get(CONF_API_TYPE, APIType.CLOUD),
    }

    # Only Overkiz cloud servers expose an endpoint with execution history
    if client.server_config.api_type == APIType.CLOUD:
        execution_history = [
            repr(execution) for execution in await client.get_execution_history()
        ]
        data["execution_history"] = execution_history

    return data


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: OverkizDataConfigEntry, device: dr.DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device entry."""
    client = entry.runtime_data.coordinator.client

    device_url = min(device.identifiers)[1]

    # A sub device is registered as a child device, which doesn't hold the details
    # of the physical device it belongs to.
    physical_device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, DeviceIdentifier.from_device_url(device_url).base_device_url),
        entry.entry_id,
    )

    if TYPE_CHECKING:
        assert physical_device

    data = {
        "device": {
            "controllable_name": physical_device.hw_version,
            "firmware": physical_device.sw_version,
            "device_url": obfuscate_id(device_url),
            "model": physical_device.model,
        },
        **await client.get_diagnostic_data(),
        "server": entry.data[CONF_HUB],
        "api_type": entry.data.get(CONF_API_TYPE, APIType.CLOUD),
    }

    # Only Overkiz cloud servers expose an endpoint with execution history
    if client.server_config.api_type == APIType.CLOUD:
        data["execution_history"] = [
            repr(execution)
            for execution in await client.get_execution_history()
            if any(
                command.device_url.split("#", 1)[0] == device_url.split("#", 1)[0]
                for command in execution.commands
            )
        ]

    return data
