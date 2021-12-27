"""Constants for the Overkiz (by Somfy) integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Final

from pyoverkiz.enums import UIClass
from pyoverkiz.enums.ui import UIWidget

from homeassistant.const import Platform

DOMAIN: Final = "overkiz"

CONF_HUB: Final = "hub"
DEFAULT_HUB: Final = "somfy_europe"

UPDATE_INTERVAL: Final = timedelta(seconds=30)
UPDATE_INTERVAL_ALL_ASSUMED_STATE: Final = timedelta(minutes=60)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.COVER,
    Platform.LOCK,
    Platform.SENSOR,
]

IGNORED_OVERKIZ_DEVICES: list[UIClass | UIWidget] = [
    UIClass.PROTOCOL_GATEWAY,
    UIClass.POD,
]

# Used to map the Somfy widget and ui_class to the Home Assistant platform
OVERKIZ_DEVICE_TO_PLATFORM: dict[UIClass | UIWidget, Platform] = {
    UIClass.ADJUSTABLE_SLATS_ROLLER_SHUTTER: Platform.COVER,
    UIClass.AWNING: Platform.COVER,
    UIClass.CURTAIN: Platform.COVER,
    UIClass.EXTERIOR_SCREEN: Platform.COVER,
    UIClass.EXTERIOR_VENETIAN_BLIND: Platform.COVER,
    UIClass.GARAGE_DOOR: Platform.COVER,
    UIClass.GATE: Platform.COVER,
    UIClass.DOOR_LOCK: Platform.LOCK,
    UIWidget.MY_FOX_SECURITY_CAMERA: Platform.COVER,  # widgetName, uiClass is Camera (not supported)
    UIClass.PERGOLA: Platform.COVER,
    UIClass.ROLLER_SHUTTER: Platform.COVER,
    UIWidget.RTS_GENERIC: Platform.COVER,  # widgetName, uiClass is Generic (not supported)
    UIClass.SCREEN: Platform.COVER,
    UIClass.SHUTTER: Platform.COVER,
    UIClass.SWINGING_SHUTTER: Platform.COVER,
    UIClass.VENETIAN_BLIND: Platform.COVER,
    UIClass.WINDOW: Platform.COVER,
}
