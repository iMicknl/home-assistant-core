"""Tahoma light platform that implements dimmable tahoma lights."""
import logging
from datetime import timedelta

from homeassistant.components.light import (
    LightEntity,
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    SUPPORT_BRIGHTNESS,
    SUPPORT_EFFECT,
)

from homeassistant.const import STATE_OFF, STATE_ON

from . import DOMAIN, TahomaDevice, TAHOMA_TYPES

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Tahoma lights from a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]

    entities = []
    controller = data.get("controller")

    for device in data.get("devices"):
        if TAHOMA_TYPES[device.uiclass] == "light":
            entities.append(TahomaLight(device, controller))

    async_add_entities(entities)


class TahomaLight(TahomaDevice, LightEntity):
    """Representation of a Tahome light"""

    def __init__(self, tahoma_device, controller):
        super().__init__(tahoma_device, controller)

        self._skip_update = False
        self._effect = None

        # TODO: 
        device_type = self.tahoma_device.widget

        if device_type == 'DimmableLight':
            # Enable brightness
            print('DimmableLight detected')

        if device_type == 'OnOffLight':
            # Disable brightness
            # TODO: Decide if we do it based on the device type or based on the available commands
            print('OnOff Light detected')

        self.update()

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        _LOGGER.debug("[THM] Called to get brightness %s" % (self._brightness))
        return int(self._brightness * (255 / 100))

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        _LOGGER.debug("[THM] Called to check is on %s" % (self._state))
        return self._state

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return SUPPORT_BRIGHTNESS | SUPPORT_EFFECT

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on."""
        _LOGGER.debug("[THM] Called to turn on (%s, %s)", kwargs, self._brightness)
        self._state = True
        self._skip_update = True

        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = int(float(kwargs[ATTR_BRIGHTNESS]) / 255 * 100)
            self.apply_action("setIntensity", self._brightness)
        elif ATTR_EFFECT in kwargs:
            self._effect = kwargs[ATTR_EFFECT]
            self.apply_action("wink", 100)
        else:
            self._brightness = 100
            self.apply_action("on")

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        _LOGGER.debug("[THM] Called to turn off")
        self._state = False
        self._skip_update = True
        self.apply_action("off")

        self.async_write_ha_state()

    @property
    def effect_list(self) -> list:
        """Return the list of supported effects."""
        return ["wink"]

    @property
    def effect(self) -> str:
        """Return the current effect."""
        return self._effect

    def update(self):
        """Fetch new state data for this light.
        This is the only method that should fetch new data for Home Assistant.
        """
        # Postpone the immediate state check for changes that take time.
        if self._skip_update:
            self._skip_update = False
            return

        _LOGGER.debug("[THM] Updating state...")
        self.controller.get_states([self.tahoma_device])
        self._brightness = self.tahoma_device.active_states.get(
            "core:LightIntensityState"
        )
        if self.tahoma_device.active_states.get("core:OnOffState") == "on":
            self._state = True
        else:
            self._state = False
