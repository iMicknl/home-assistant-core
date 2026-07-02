"""Support for Overkiz (virtual) buttons."""

from dataclasses import dataclass, replace
from typing import override

from pyoverkiz.enums import OverkizAttribute, OverkizCommand, OverkizCommandParam
from pyoverkiz.models import Device
from pyoverkiz.types import StateType as OverkizStateType

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OverkizDataConfigEntry
from .const import IGNORED_OVERKIZ_DEVICES
from .coordinator import OverkizDataUpdateCoordinator
from .entity import OverkizDescriptiveEntity

# Alias id 1 (favorite1) is the "My position" preset on DynamicScreen (ogp:blind)
FAVORITE_ALIAS_ID = "1"
FAVORITE_ALIAS_TYPE = "favorite1"


@dataclass(frozen=True)
class OverkizButtonDescription(ButtonEntityDescription):
    """Class to describe an Overkiz button."""

    press_args: OverkizStateType | None = None
    # Command to execute, when it differs from the (unique) description key
    command: OverkizCommand | None = None


BUTTON_DESCRIPTIONS: list[OverkizButtonDescription] = [
    # My Position (cover, light)
    OverkizButtonDescription(
        key=OverkizCommand.MY,
        name="My position",
        icon="mdi:star",
    ),
    # Identify
    OverkizButtonDescription(
        # startIdentify and identify are reversed... Swap this when fixed in API.
        key=OverkizCommand.IDENTIFY,
        name="Start identify",
        icon="mdi:human-greeting-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    OverkizButtonDescription(
        key=OverkizCommand.STOP_IDENTIFY,
        name="Stop identify",
        icon="mdi:human-greeting-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    OverkizButtonDescription(
        # startIdentify and identify are reversed... Swap this when fixed in API.
        key=OverkizCommand.START_IDENTIFY,
        name="Identify",
        icon="mdi:human-greeting-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=ButtonDeviceClass.IDENTIFY,
    ),
    # RTDIndoorSiren / RTDOutdoorSiren
    OverkizButtonDescription(
        key=OverkizCommand.DING_DONG, name="Ding dong", icon="mdi:bell-ring"
    ),
    OverkizButtonDescription(key=OverkizCommand.BIP, name="Bip", icon="mdi:bell-ring"),
    OverkizButtonDescription(
        key=OverkizCommand.FAST_BIP_SEQUENCE,
        name="Fast bip sequence",
        icon="mdi:bell-ring",
    ),
    OverkizButtonDescription(
        key=OverkizCommand.RING, name="Ring", icon="mdi:bell-ring"
    ),
    # DynamicScreen (ogp:blind) uses goToAlias (id 1: favorite1) instead of 'my'
    OverkizButtonDescription(
        key=OverkizCommand.GO_TO_ALIAS,
        press_args="1",
        name="My position",
        icon="mdi:star",
    ),
    OverkizButtonDescription(
        key=OverkizCommand.CYCLE,
        name="Toggle",
        icon="mdi:sync",
    ),
    # SmokeSensor
    OverkizButtonDescription(
        key=OverkizCommand.CHECK_EVENT_TRIGGER,
        press_args=OverkizCommandParam.SHORT,
        name="Test",
        icon="mdi:smoke-detector",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]

SUPPORTED_COMMANDS = {
    description.key: description for description in BUTTON_DESCRIPTIONS
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OverkizDataConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Overkiz button from a config entry."""
    data = entry.runtime_data
    entities: list[ButtonEntity] = []

    for device in data.coordinator.data.values():
        if (
            device.widget in IGNORED_OVERKIZ_DEVICES
            or device.ui_class in IGNORED_OVERKIZ_DEVICES
        ):
            continue

        for command in device.definition.commands:
            if not (description := SUPPORTED_COMMANDS.get(command)):
                continue

            if command == OverkizCommand.GO_TO_ALIAS:
                entities.extend(
                    _create_go_to_alias_buttons(device, data.coordinator)
                )
                continue

            entities.append(
                OverkizButton(device.device_url, data.coordinator, description)
            )

    async_add_entities(entities)


def _create_go_to_alias_buttons(
    device: Device, coordinator: OverkizDataUpdateCoordinator
) -> list[OverkizButton]:
    """Create goToAlias buttons for the aliases the device actually exposes.

    The default press_args of "1" (favorite1) is only valid on DynamicScreen
    (ogp:blind); other devices expose their own alias ids in
    core:SupportedAliases (e.g. a Velux ventilation position), so pressing a
    hardcoded "1" button fails. Create one button per real alias id instead.
    """
    aliases: list[dict] = []
    if attribute := device.attributes.get(OverkizAttribute.CORE_SUPPORTED_ALIASES):
        aliases = attribute.value

    # Without a SupportedAliases attribute we keep the legacy favorite1 button
    # for backwards compatibility (e.g. ogp:Pergola exposes goToAlias only).
    if not aliases:
        return [
            OverkizButton(
                device.device_url,
                coordinator,
                SUPPORTED_COMMANDS[OverkizCommand.GO_TO_ALIAS],
            )
        ]

    buttons: list[OverkizButton] = []

    # Keep the single "My position" button (unchanged unique_id) only when the
    # favorite1 preset id 1 is actually present.
    if any(alias["id"] == FAVORITE_ALIAS_ID for alias in aliases):
        buttons.append(
            OverkizButton(
                device.device_url,
                coordinator,
                SUPPORTED_COMMANDS[OverkizCommand.GO_TO_ALIAS],
            )
        )

    # Expose the remaining named presets (e.g. a Velux ventilation position).
    for alias in aliases:
        if alias["type"] == FAVORITE_ALIAS_TYPE:
            continue

        alias_id = alias["id"]
        alias_type = alias["type"]
        buttons.append(
            OverkizButton(
                device.device_url,
                coordinator,
                replace(
                    SUPPORTED_COMMANDS[OverkizCommand.GO_TO_ALIAS],
                    key=f"{OverkizCommand.GO_TO_ALIAS}-{alias_id}",
                    command=OverkizCommand.GO_TO_ALIAS,
                    press_args=alias_id,
                    name=alias_type.capitalize(),
                    translation_key=alias_type,
                ),
            )
        )

    return buttons


class OverkizButton(OverkizDescriptiveEntity, ButtonEntity):
    """Representation of an Overkiz Button."""

    entity_description: OverkizButtonDescription

    @override
    async def async_press(self) -> None:
        """Handle the button press."""
        command = self.entity_description.command or self.entity_description.key

        if self.entity_description.press_args:
            await self.executor.async_execute_command(
                command, self.entity_description.press_args
            )
            return

        await self.executor.async_execute_command(command)
