"""Parent class for every Overkiz device."""

from typing import cast, override

from pyoverkiz.enums import APIType, OverkizAttribute, OverkizCommandParam, OverkizState
from pyoverkiz.models import Device

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WIDGET_TO_MANUFACTURER
from .coordinator import OverkizDataUpdateCoordinator
from .executor import OverkizExecutor


@callback
def async_device_info(
    coordinator: OverkizDataUpdateCoordinator, device: Device
) -> DeviceInfo:
    """Return device registry information for a physical Overkiz device."""
    manufacturer = (
        WIDGET_TO_MANUFACTURER.get(device.widget)
        or device.attributes.get_value(OverkizAttribute.CORE_MANUFACTURER)
        or device.states.get_value(OverkizState.CORE_MANUFACTURER_NAME)
        or coordinator.client.server_config.manufacturer
    )

    model = (
        device.states.first_value(
            [
                OverkizState.CORE_MODEL,
                OverkizState.CORE_PRODUCT_MODEL_NAME,
                OverkizState.IO_MODEL,
            ]
        )
        or device.ui_class.value
    )

    return DeviceInfo(
        identifiers={(DOMAIN, device.identifier.base_device_url)},
        name=device.label,
        manufacturer=str(manufacturer),
        model=str(model),
        sw_version=cast(
            str,
            device.attributes.get_value(OverkizAttribute.CORE_FIRMWARE_REVISION),
        ),
        model_id=device.widget,
        hw_version=device.controllable_name,
        suggested_area=async_suggested_area(coordinator, device),
        via_device_id=dr.async_get_device_id_by_identifier(
            coordinator.hass,
            (DOMAIN, device.identifier.gateway_id),
            config_entry_id=coordinator.config_entry.entry_id,
        ),
        configuration_url=coordinator.client.server_config.configuration_url,
    )


@callback
def async_suggested_area(
    coordinator: OverkizDataUpdateCoordinator, device: Device
) -> str | None:
    """Return the area suggested by the place of the device."""
    if coordinator.areas and device.place_oid:
        return coordinator.areas[device.place_oid]

    return None


class OverkizEntity(CoordinatorEntity[OverkizDataUpdateCoordinator]):
    """Representation of an Overkiz device entity."""

    _attr_has_entity_name = True
    _attr_name: str | None = None
    _attr_device_info: DeviceInfo | ChildDeviceInfo | None = None

    def __init__(
        self, device_url: str, coordinator: OverkizDataUpdateCoordinator
    ) -> None:
        """Initialize the device."""
        super().__init__(coordinator)
        self.device_url = device_url
        self.executor = OverkizExecutor(device_url, coordinator)

        self._attr_assumed_state = not self.device.states
        self._attr_unique_id = self.device.device_url

        self._attr_device_info = self.generate_device_info()

    @property
    @override
    def available(self) -> bool:
        """Return True if entity is available."""
        if self.device.available:
            return super().available

        # Workaround: local API may incorrectly report
        # available=False (Somfy-TaHoma-Developer-Mode#217)
        if self.coordinator.client.server_config.api_type != APIType.LOCAL:
            return False

        if status_state := self.device.states.get(OverkizState.CORE_STATUS):
            return (
                status_state.value == OverkizCommandParam.AVAILABLE
                and super().available
            )

        return False

    @property
    def device(self) -> Device:
        """Return Overkiz device linked to this entity."""
        return self.coordinator.data[self.device_url]

    def generate_device_info(self) -> DeviceInfo | ChildDeviceInfo:
        """Return device registry information for this entity."""
        # Some devices, such as the Smart Thermostat have several devices
        # in one physical device, with same device url, terminated by '#' and a number.
        # Those sub devices are registered as child devices of the physical device,
        # which is registered during the setup of the config entry.
        if self.device.identifier.is_sub_device:
            return ChildDeviceInfo(
                identifiers={(DOMAIN, self.device.device_url)},
                name=self.device.label,
                parent_device_id=dr.async_get_device_id_by_identifier(
                    self.coordinator.hass,
                    (DOMAIN, self.device.identifier.base_device_url),
                    config_entry_id=self.coordinator.config_entry.entry_id,
                ),
                suggested_area=async_suggested_area(self.coordinator, self.device),
            )

        return async_device_info(self.coordinator, self.device)


class OverkizDescriptiveEntity(OverkizEntity):
    """Representation of a Overkiz device entity based on a description."""

    def __init__(
        self,
        device_url: str,
        coordinator: OverkizDataUpdateCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialize the device."""
        super().__init__(device_url, coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}-{self.entity_description.key}"

        if isinstance(description.name, str):
            self._attr_name = description.name
