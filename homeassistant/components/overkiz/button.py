"""Support for Overkiz (virtual) buttons."""

from dataclasses import dataclass
from typing import override

from pyoverkiz.enums import (
    OverkizCommand,
    OverkizCommandParam,
    UIClass,
    UpdateBoxStatus,
)
from pyoverkiz.types import StateType as OverkizStateType

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OverkizDataConfigEntry
from .const import DOMAIN, GATEWAY_UPDATE_READY_STATUSES, IGNORED_OVERKIZ_DEVICES
from .coordinator import OverkizGatewayCoordinator
from .entity import OverkizDescriptiveEntity, OverkizGatewayEntity
from .executor import OverkizExecutor


@dataclass(frozen=True)
class OverkizButtonDescription(ButtonEntityDescription):
    """Class to describe an Overkiz button."""

    press_args: list[OverkizStateType] | None = None


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
        press_args=["1"],
        name="My position",
        icon="mdi:star",
    ),
    OverkizButtonDescription(
        key=OverkizCommand.CYCLE,
        name="Toggle",
        icon="mdi:sync",
    ),
    # DimmerOnOffLight (rts:DimmableLightRTSComponent)
    OverkizButtonDescription(
        key=OverkizCommand.STEP_POSITIVE,
        name="Brightness up",
        icon="mdi:brightness-7",
        # step (0-127), execution duration (0-15, optional)
        press_args=[5],
    ),
    OverkizButtonDescription(
        key=OverkizCommand.STEP_NEGATIVE,
        name="Brightness down",
        icon="mdi:brightness-3",
        # step (0-127), execution duration (0-15, optional)
        press_args=[5],
    ),
    # SmokeSensor
    OverkizButtonDescription(
        key=OverkizCommand.CHECK_EVENT_TRIGGER,
        press_args=[OverkizCommandParam.SHORT],
        name="Test",
        icon="mdi:smoke-detector",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]

GATEWAY_FIRMWARE_UPDATE_BUTTON = ButtonEntityDescription(
    key="install_firmware_update",
    translation_key="install_firmware_update",
    device_class=ButtonDeviceClass.UPDATE,
    entity_category=EntityCategory.CONFIG,
)

SUPPORTED_COMMANDS = {
    description.key: description for description in BUTTON_DESCRIPTIONS
}


PARALLEL_UPDATES = 0


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

        entities.extend(
            OverkizButton(
                device.device_url,
                data.coordinator,
                description,
            )
            for command in device.definition.commands
            if (description := SUPPORTED_COMMANDS.get(command))
        )

    if gateway_coordinator := data.gateway_coordinator:
        # The firmware update is triggered through the gateway's pod device.
        for device in data.coordinator.data.values():
            if (
                device.ui_class != UIClass.POD
                or OverkizCommand.UPDATE not in device.definition.commands
                or not (
                    gateway := gateway_coordinator.data.get(
                        device.identifier.gateway_id
                    )
                )
                or gateway.update_status in (None, UpdateBoxStatus.NOT_UPDATABLE)
            ):
                continue

            entities.append(
                OverkizGatewayFirmwareUpdateButton(
                    gateway.id,
                    gateway_coordinator,
                    OverkizExecutor(device.device_url, data.coordinator),
                )
            )

    async_add_entities(entities)


class OverkizButton(OverkizDescriptiveEntity, ButtonEntity):
    """Representation of an Overkiz Button."""

    entity_description: OverkizButtonDescription

    @override
    async def async_press(self) -> None:
        """Handle the button press."""
        if (press_args := self.entity_description.press_args) is not None:
            await self.executor.async_execute_command(
                self.entity_description.key, *press_args
            )
            return

        await self.executor.async_execute_command(self.entity_description.key)


class OverkizGatewayFirmwareUpdateButton(OverkizGatewayEntity, ButtonEntity):
    """Representation of an Overkiz gateway firmware update button."""

    def __init__(
        self,
        gateway_id: str,
        coordinator: OverkizGatewayCoordinator,
        executor: OverkizExecutor,
    ) -> None:
        """Initialize the button."""
        super().__init__(gateway_id, coordinator, GATEWAY_FIRMWARE_UPDATE_BUTTON)
        self.executor = executor

    @override
    async def async_press(self) -> None:
        """Install the pending firmware update."""
        if self.gateway.update_status not in GATEWAY_UPDATE_READY_STATUSES:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_firmware_update_available",
            )

        await self.executor.async_execute_command(OverkizCommand.UPDATE)
