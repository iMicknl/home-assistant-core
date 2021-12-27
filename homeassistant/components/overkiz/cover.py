"""Support for Overkiz covers - shutters etc."""
from pyoverkiz.enums import UIClass

from homeassistant.components.cover import CoverEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeAssistantOverkizData
from .const import DOMAIN
from .cover_devices.awning import Awning
from .cover_devices.vertical_cover import VerticalCover


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up the Overkiz covers from a config entry."""
    data: HomeAssistantOverkizData = hass.data[DOMAIN][entry.entry_id]

    entities: list[CoverEntity] = [
        Awning(device.device_url, data.coordinator)
        for device in data.platforms[Platform.COVER]
        if device.ui_class == UIClass.AWNING
    ]

    entities += [
        VerticalCover(device.device_url, data.coordinator)
        for device in data.platforms[Platform.COVER]
        if device.ui_class != UIClass.AWNING
    ]

    async_add_entities(entities)
