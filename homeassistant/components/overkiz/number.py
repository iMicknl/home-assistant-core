"""Support for Overkiz (virtual) numbers."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from pyoverkiz.enums import OverkizCommand, OverkizCommandParam, OverkizState
from pyoverkiz.models import Command

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OverkizDataConfigEntry
from .const import IGNORED_OVERKIZ_DEVICES
from .coordinator import OverkizDataUpdateCoordinator
from .entity import OverkizDescriptiveEntity


@dataclass(frozen=True, kw_only=True)
class OverkizNumberDescription(NumberEntityDescription):
    """Class to describe an Overkiz number."""

    command: str

    min_value_state_name: str | None = None
    max_value_state_name: str | None = None
    inverted: bool = False
    set_native_value: Callable[[float], list[Command]] | None = None


def _boost_mode_duration_commands(value: float) -> list[Command]:
    """Build the boost-duration command sequence."""
    if value > 0:
        relaunch = OverkizCommandParam.ON
        commands = [
            Command(name=OverkizCommand.SET_BOOST_MODE_DURATION, parameters=[value])
        ]
    else:
        relaunch = OverkizCommandParam.OFF
        commands = []

    commands.append(
        Command(
            name=OverkizCommand.SET_CURRENT_OPERATING_MODE,
            parameters=[
                {
                    OverkizCommandParam.RELAUNCH: relaunch,
                    OverkizCommandParam.ABSENCE: OverkizCommandParam.OFF,
                }
            ],
        )
    )
    # One action group is a single poll, so the new duration is read back
    # without the per-execution settle delays the old flow needed.
    commands.append(Command(name=OverkizCommand.REFRESH_BOOST_MODE_DURATION))
    return commands


NUMBER_DESCRIPTIONS: list[OverkizNumberDescription] = [
    # Cover: My Position (0 - 100)
    OverkizNumberDescription(
        key=OverkizState.CORE_MEMORIZED_1_POSITION,
        name="My position",
        icon="mdi:content-save-cog",
        command=OverkizCommand.SET_MEMORIZED_1_POSITION,
        native_min_value=0,
        native_max_value=100,
        entity_category=EntityCategory.CONFIG,
    ),
    # WaterHeater: Expected Number Of Shower (2 - 4)
    OverkizNumberDescription(
        key=OverkizState.CORE_EXPECTED_NUMBER_OF_SHOWER,
        name="Expected number of shower",
        icon="mdi:shower-head",
        command=OverkizCommand.SET_EXPECTED_NUMBER_OF_SHOWER,
        native_min_value=2,
        native_max_value=4,
        min_value_state_name=OverkizState.CORE_MINIMAL_SHOWER_MANUAL_MODE,
        max_value_state_name=OverkizState.CORE_MAXIMAL_SHOWER_MANUAL_MODE,
        entity_category=EntityCategory.CONFIG,
    ),
    OverkizNumberDescription(
        key=OverkizState.CORE_TARGET_DWH_TEMPERATURE,
        name="Target temperature",
        device_class=NumberDeviceClass.TEMPERATURE,
        command=OverkizCommand.SET_TARGET_DHW_TEMPERATURE,
        native_min_value=50,
        native_max_value=65,
        min_value_state_name=OverkizState.CORE_MINIMAL_TEMPERATURE_MANUAL_MODE,
        max_value_state_name=OverkizState.CORE_MAXIMAL_TEMPERATURE_MANUAL_MODE,
        entity_category=EntityCategory.CONFIG,
    ),
    OverkizNumberDescription(
        key=OverkizState.CORE_WATER_TARGET_TEMPERATURE,
        name="Water target temperature",
        device_class=NumberDeviceClass.TEMPERATURE,
        command=OverkizCommand.SET_WATER_TARGET_TEMPERATURE,
        native_min_value=50,
        native_max_value=65,
        min_value_state_name=OverkizState.CORE_MINIMAL_TEMPERATURE_MANUAL_MODE,
        max_value_state_name=OverkizState.CORE_MAXIMAL_TEMPERATURE_MANUAL_MODE,
        entity_category=EntityCategory.CONFIG,
    ),
    # SomfyHeatingTemperatureInterface
    OverkizNumberDescription(
        key=OverkizState.CORE_ECO_ROOM_TEMPERATURE,
        name="Eco room temperature",
        icon="mdi:thermometer",
        command=OverkizCommand.SET_ECO_TEMPERATURE,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=6,
        native_max_value=29,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.CONFIG,
    ),
    OverkizNumberDescription(
        key=OverkizState.CORE_COMFORT_ROOM_TEMPERATURE,
        name="Comfort room temperature",
        icon="mdi:home-thermometer-outline",
        command=OverkizCommand.SET_COMFORT_TEMPERATURE,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=7,
        native_max_value=30,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.CONFIG,
    ),
    OverkizNumberDescription(
        key=OverkizState.CORE_SECURED_POSITION_TEMPERATURE,
        name="Freeze protection temperature",
        icon="mdi:sun-thermometer-outline",
        command=OverkizCommand.SET_SECURED_POSITION_TEMPERATURE,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=5,
        native_max_value=15,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.CONFIG,
    ),
    # DimmerExteriorHeating (Somfy Terrace Heater) (0 - 100)
    # Needs to be inverted since 100 = off, 0 = on
    OverkizNumberDescription(
        key=OverkizState.CORE_LEVEL,
        icon="mdi:patio-heater",
        command=OverkizCommand.SET_LEVEL,
        native_min_value=0,
        native_max_value=100,
        inverted=True,
    ),
    # DomesticHotWaterProduction - boost mode duration in days (0 - 7)
    OverkizNumberDescription(
        key=OverkizState.CORE_BOOST_MODE_DURATION,
        name="Boost mode duration",
        icon="mdi:water-boiler",
        command=OverkizCommand.SET_BOOST_MODE_DURATION,
        native_min_value=0,
        native_max_value=7,
        set_native_value=_boost_mode_duration_commands,
        entity_category=EntityCategory.CONFIG,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
    ),
    # DomesticHotWaterProduction - away mode in days (0 - 6)
    OverkizNumberDescription(
        key=OverkizState.IO_AWAY_MODE_DURATION,
        name="Away mode duration",
        icon="mdi:water-boiler-off",
        command=OverkizCommand.SET_AWAY_MODE_DURATION,
        native_min_value=0,
        native_max_value=6,
        entity_category=EntityCategory.CONFIG,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
    ),
]

SUPPORTED_STATES = {description.key: description for description in NUMBER_DESCRIPTIONS}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OverkizDataConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Overkiz number from a config entry."""
    data = entry.runtime_data
    entities: list[OverkizNumber] = []

    for device in data.coordinator.data.values():
        if (
            device.widget in IGNORED_OVERKIZ_DEVICES
            or device.ui_class in IGNORED_OVERKIZ_DEVICES
        ):
            continue

        entities.extend(
            OverkizNumber(
                device.device_url,
                data.coordinator,
                description,
            )
            for state in device.definition.states
            if (description := SUPPORTED_STATES.get(state))
        )

    async_add_entities(entities)


class OverkizNumber(OverkizDescriptiveEntity, NumberEntity):
    """Representation of an Overkiz Number."""

    entity_description: OverkizNumberDescription

    def __init__(
        self,
        device_url: str,
        coordinator: OverkizDataUpdateCoordinator,
        description: OverkizNumberDescription,
    ) -> None:
        """Initialize a device."""
        super().__init__(device_url, coordinator, description)

        if (
            self.entity_description.min_value_state_name
            and (
                value := self.device.states.get_value(
                    self.entity_description.min_value_state_name
                )
            )
            is not None
        ):
            self._attr_native_min_value = cast(float, value)

        if (
            self.entity_description.max_value_state_name
            and (
                value := self.device.states.get_value(
                    self.entity_description.max_value_state_name
                )
            )
            is not None
        ):
            self._attr_native_max_value = cast(float, value)

    @property
    def native_value(self) -> float | None:
        """Return the entity value to represent the entity state."""
        if (
            value := self.device.states.get_value(self.entity_description.key)
        ) is not None:
            if self.entity_description.inverted:
                return self.native_max_value - cast(float, value)

            return cast(float, value)

        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        if self.entity_description.inverted:
            value = self.native_max_value - value

        if self.entity_description.set_native_value:
            await self.executor.async_execute_commands(
                self.entity_description.set_native_value(value)
            )
            return

        await self.executor.async_execute_command(
            self.entity_description.command, [value]
        )
