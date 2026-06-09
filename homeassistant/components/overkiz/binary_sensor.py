"""Support for Overkiz binary sensors."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from pyoverkiz.enums import OverkizCommandParam, OverkizState, UpdateBoxStatus
from pyoverkiz.models import Gateway
from pyoverkiz.types import StateType as OverkizStateType

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OverkizDataConfigEntry
from .const import DOMAIN, IGNORED_OVERKIZ_DEVICES
from .coordinator import OverkizDataUpdateCoordinator
from .entity import OverkizDescriptiveEntity


@dataclass(frozen=True, kw_only=True)
class OverkizBinarySensorDescription(BinarySensorEntityDescription):
    """Class to describe an Overkiz binary sensor."""

    value_fn: Callable[[OverkizStateType], bool]


BINARY_SENSOR_DESCRIPTIONS: list[OverkizBinarySensorDescription] = [
    # RainSensor/RainSensor
    OverkizBinarySensorDescription(
        key=OverkizState.CORE_RAIN,
        name="Rain",
        icon="mdi:weather-rainy",
        value_fn=lambda state: state == OverkizCommandParam.DETECTED,
    ),
    # SmokeSensor/SmokeSensor
    OverkizBinarySensorDescription(
        key=OverkizState.CORE_SMOKE,
        name="Smoke",
        device_class=BinarySensorDeviceClass.SMOKE,
        value_fn=lambda state: state == OverkizCommandParam.DETECTED,
    ),
    # WaterSensor/WaterDetectionSensor
    OverkizBinarySensorDescription(
        key=OverkizState.CORE_WATER_DETECTION,
        name="Water",
        icon="mdi:water",
        device_class=BinarySensorDeviceClass.MOISTURE,
        value_fn=lambda state: state == OverkizCommandParam.DETECTED,
    ),
    # AirSensor/AirFlowSensor
    OverkizBinarySensorDescription(
        key=OverkizState.CORE_GAS_DETECTION,
        name="Gas",
        device_class=BinarySensorDeviceClass.GAS,
        value_fn=lambda state: state == OverkizCommandParam.DETECTED,
    ),
    # OccupancySensor/OccupancySensor
    # OccupancySensor/MotionSensor
    OverkizBinarySensorDescription(
        key=OverkizState.CORE_OCCUPANCY,
        name="Occupancy",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        value_fn=lambda state: state == OverkizCommandParam.PERSON_INSIDE,
    ),
    # ContactSensor/WindowWithTiltSensor
    OverkizBinarySensorDescription(
        key=OverkizState.CORE_VIBRATION,
        name="Vibration",
        device_class=BinarySensorDeviceClass.VIBRATION,
        value_fn=lambda state: state == OverkizCommandParam.DETECTED,
    ),
    # ContactSensor/ContactSensor
    OverkizBinarySensorDescription(
        key=OverkizState.CORE_CONTACT,
        name="Contact",
        device_class=BinarySensorDeviceClass.DOOR,
        value_fn=lambda state: state == OverkizCommandParam.OPEN,
    ),
    # Siren/SirenStatus
    OverkizBinarySensorDescription(
        key=OverkizState.CORE_ASSEMBLY,
        name="Assembly",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda state: state == OverkizCommandParam.OPEN,
    ),
    # Unknown
    OverkizBinarySensorDescription(
        key=OverkizState.IO_VIBRATION_DETECTED,
        name="Vibration",
        device_class=BinarySensorDeviceClass.VIBRATION,
        value_fn=lambda state: state == OverkizCommandParam.DETECTED,
    ),
    # DomesticHotWaterProduction/WaterHeatingSystem
    OverkizBinarySensorDescription(
        key=OverkizState.IO_OPERATING_MODE_CAPABILITIES,
        name="Energy demand status",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda state: (
            cast(dict, state).get(OverkizCommandParam.ENERGY_DEMAND_STATUS) == 1
        ),
    ),
    OverkizBinarySensorDescription(
        key=OverkizState.CORE_HEATING_STATUS,
        name="Heating status",
        device_class=BinarySensorDeviceClass.HEAT,
        value_fn=lambda state: (
            cast(str, state).lower()
            in (OverkizCommandParam.ON, OverkizCommandParam.HEATING)
        ),
    ),
    OverkizBinarySensorDescription(
        key=OverkizState.MODBUSLINK_DHW_ABSENCE_MODE,
        name="Absence mode",
        value_fn=(
            lambda state: state in (OverkizCommandParam.ON, OverkizCommandParam.PROG)
        ),
    ),
    OverkizBinarySensorDescription(
        key=OverkizState.MODBUSLINK_DHW_BOOST_MODE,
        name="Boost mode",
        value_fn=(
            lambda state: state in (OverkizCommandParam.ON, OverkizCommandParam.PROG)
        ),
    ),
    OverkizBinarySensorDescription(
        key=OverkizState.MODBUSLINK_DHW_MODE,
        name="Manual mode",
        value_fn=(
            lambda state: (
                state
                in (OverkizCommandParam.MANUAL, OverkizCommandParam.MANUAL_ECO_INACTIVE)
            )
        ),
    ),
]

SUPPORTED_STATES = {
    description.key: description for description in BINARY_SENSOR_DESCRIPTIONS
}


# Update box statuses that indicate a firmware update is available to install.
UPDATE_AVAILABLE_STATUSES = (
    UpdateBoxStatus.READY_TO_UPDATE,
    UpdateBoxStatus.READY_TO_BE_UPDATED_BY_SERVER,
    UpdateBoxStatus.READY_TO_UPDATE_LOCALLY,
)


def _update_available(gateway: Gateway) -> bool | None:
    """Return whether a firmware update is available, or None if unknown."""
    if (
        gateway.update_status is None
        or gateway.update_status == UpdateBoxStatus.UNKNOWN
    ):
        return None
    return gateway.update_status in UPDATE_AVAILABLE_STATUSES


@dataclass(frozen=True, kw_only=True)
class OverkizGatewayBinarySensorDescription(BinarySensorEntityDescription):
    """Class to describe an Overkiz gateway binary sensor."""

    value_fn: Callable[[Gateway], bool | None]
    # Only create the entity when the gateway actually exposes the field.
    # The local API, for example, does not report alive or update status.
    exists_fn: Callable[[Gateway], bool]


GATEWAY_BINARY_SENSOR_DESCRIPTIONS: list[OverkizGatewayBinarySensorDescription] = [
    OverkizGatewayBinarySensorDescription(
        key="connectivity",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda gateway: gateway.alive,
        exists_fn=lambda gateway: gateway.alive is not None,
    ),
    OverkizGatewayBinarySensorDescription(
        key="update",
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_update_available,
        exists_fn=lambda gateway: gateway.update_status is not None,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OverkizDataConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Overkiz binary sensors from a config entry."""
    data = entry.runtime_data
    entities: list[BinarySensorEntity] = []

    for device in data.coordinator.data.values():
        if (
            device.widget in IGNORED_OVERKIZ_DEVICES
            or device.ui_class in IGNORED_OVERKIZ_DEVICES
        ):
            continue

        entities.extend(
            OverkizBinarySensor(
                device.device_url,
                data.coordinator,
                description,
            )
            for state in device.definition.states
            if (description := SUPPORTED_STATES.get(state))
        )

    entities.extend(
        OverkizGatewayBinarySensor(gateway.id, data.coordinator, description)
        for gateway in data.coordinator.gateways.values()
        for description in GATEWAY_BINARY_SENSOR_DESCRIPTIONS
        if description.exists_fn(gateway)
    )

    async_add_entities(entities)


class OverkizBinarySensor(OverkizDescriptiveEntity, BinarySensorEntity):
    """Representation of an Overkiz Binary Sensor."""

    entity_description: OverkizBinarySensorDescription

    @property
    def is_on(self) -> bool | None:
        """Return the state of the sensor."""
        if state := self.device.states.get(self.entity_description.key):
            return self.entity_description.value_fn(state.value)

        return None


class OverkizGatewayBinarySensor(
    CoordinatorEntity[OverkizDataUpdateCoordinator], BinarySensorEntity
):
    """Representation of an Overkiz gateway binary sensor."""

    entity_description: OverkizGatewayBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        gateway_id: str,
        coordinator: OverkizDataUpdateCoordinator,
        description: OverkizGatewayBinarySensorDescription,
    ) -> None:
        """Initialize the gateway binary sensor."""
        super().__init__(coordinator)
        self.gateway_id = gateway_id
        self.entity_description = description
        self._attr_unique_id = f"{gateway_id}-{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, gateway_id)},
        )

    @property
    def is_on(self) -> bool | None:
        """Return the state of the sensor."""
        return self.entity_description.value_fn(
            self.coordinator.gateways[self.gateway_id]
        )
