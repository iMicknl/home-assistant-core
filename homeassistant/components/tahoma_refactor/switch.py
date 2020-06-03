"""Support for Tahoma switches."""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON

from . import TahomaDevice
from .const import DOMAIN, TAHOMA_TYPES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Tahoma sensors from a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]

    entities = []
    controller = data.get("controller")

    for device in data.get("devices"):
        if TAHOMA_TYPES[device.uiclass] == "sensor":
            entities.append(TahomaSwitch(device, controller))

    async_add_entities(entities)


class TahomaSwitch(TahomaDevice, SwitchEntity):
    """Representation a Tahoma Switch."""

    def __init__(self, tahoma_device, controller):
        """Initialize the switch."""
        super().__init__(tahoma_device, controller)
        self._state = STATE_OFF
        self._skip_update = False
        self._available = False

    def update(self):
        """Update method."""
        # Postpone the immediate state check for changes that take time.
        if self._skip_update:
            self._skip_update = False
            return

        self.controller.get_states([self.tahoma_device])

        # A RTS power socket doesn't have a feedback channel,
        # so we must assume the socket is available.
        if self.tahoma_device.type == "rts:OnOffRTSComponent":
            self._available = True
        else:
            self._available = bool(
                self.tahoma_device.active_states.get("core:StatusState") == "available"
            )

        _LOGGER.debug("Update %s, state: %s", self._name, self._state)

    @property
    def device_class(self):
        """Return the class of the device."""
        if self.tahoma_device.type == "rts:GarageDoor4TRTSComponent":
            return "garage"
        return None

    def turn_on(self, **kwargs):
        """Send the on command."""
        _LOGGER.debug("Turn on: %s", self._name)
        if self.tahoma_device.type == "rts:GarageDoor4TRTSComponent":
            self.toggle()
        else:
            self.apply_action("on")
            self._skip_update = True
            self._state = STATE_ON

    def turn_off(self, **kwargs):
        """Send the off command."""
        _LOGGER.debug("Turn off: %s", self._name)
        if self.tahoma_device.type == "rts:GarageDoor4TRTSComponent":
            return

        self.apply_action("off")
        self._skip_update = True
        self._state = STATE_OFF

    def toggle(self, **kwargs):
        """Click the switch."""
        self.apply_action("cycle")

    @property
    def is_on(self):
        """Get whether the switch is in on state."""
        if self.tahoma_device.type == "rts:GarageDoor4TRTSComponent":
            return False
        return bool(self._state == STATE_ON)

    @property
    def available(self):
        """Return True if entity is available."""
        return self._available
