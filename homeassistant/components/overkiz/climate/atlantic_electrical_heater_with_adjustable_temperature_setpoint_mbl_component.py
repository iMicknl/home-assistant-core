"""Support for Atlantic Electrical Heater With Adjustable Temperature Setpoint (modbuslink)."""

from typing import Any, override

from pyoverkiz.enums import OverkizCommand, OverkizCommandParam, OverkizState
from pyoverkiz.models import Command

from homeassistant.components.climate import (
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from ..const import DOMAIN
from ..coordinator import OverkizDataUpdateCoordinator
from ..entity import OverkizEntity

OVERKIZ_TO_HVAC_MODE: dict[str, HVACMode] = {
    OverkizCommandParam.MANUAL: HVACMode.HEAT,
    OverkizCommandParam.PROG: HVACMode.AUTO,
    OverkizCommandParam.AUTO: HVACMode.AUTO,
}

HVAC_MODE_TO_OVERKIZ: dict[HVACMode, str] = {
    HVACMode.HEAT: OverkizCommandParam.MANUAL,
    HVACMode.AUTO: OverkizCommandParam.PROG,
}

OVERKIZ_TO_PRESET_MODE: dict[str, str] = {
    OverkizCommandParam.COMFORT: PRESET_COMFORT,
    OverkizCommandParam.ECO: PRESET_ECO,
    OverkizCommandParam.BOOST: PRESET_BOOST,
}

PRESET_MODE_TO_OVERKIZ = {v: k for k, v in OVERKIZ_TO_PRESET_MODE.items()}

TEMPERATURE_SENSOR_DEVICE_INDEX = 2


class AtlanticElectricalHeaterWithAdjustableTemperatureSetpointMBLComponent(
    OverkizEntity, ClimateEntity
):
    """Representation of Atlantic Electrical Heater (modbuslink).

    With Adjustable Temperature Setpoint.
    """

    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    _attr_preset_modes = [*PRESET_MODE_TO_OVERKIZ]
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_translation_key = DOMAIN

    def __init__(
        self, device_url: str, coordinator: OverkizDataUpdateCoordinator
    ) -> None:
        """Init method."""
        super().__init__(device_url, coordinator)
        self.temperature_device = self.executor.linked_device(
            TEMPERATURE_SENSOR_DEVICE_INDEX
        )

    @property
    @override
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation ie. heat, cool mode."""
        states = self.device.states
        # Switching off keeps the operating mode, so on/off takes precedence.
        if (
            on_off := states.get(OverkizState.CORE_ON_OFF)
        ) and on_off.value_as_str == OverkizCommandParam.OFF:
            return HVACMode.OFF
        if (
            operating_mode := states.get(OverkizState.CORE_OPERATING_MODE)
        ) and operating_mode.value_as_str:
            return OVERKIZ_TO_HVAC_MODE.get(operating_mode.value_as_str)
        return None

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return

        commands = [
            Command(
                name=OverkizCommand.SET_ON_OFF, parameters=[OverkizCommandParam.ON]
            ),
            Command(
                name=OverkizCommand.SET_OPERATING_MODE,
                parameters=[HVAC_MODE_TO_OVERKIZ[hvac_mode]],
            ),
        ]
        # The schedule picks the heating level, the Cozytouch app refreshes it too.
        if hvac_mode == HVACMode.AUTO:
            commands.append(Command(name=OverkizCommand.REFRESH_HEATING_LEVEL))
        await self.executor.async_execute_commands(commands)

    @override
    async def async_turn_on(self) -> None:
        """Turn the heater on in its last operating mode."""
        await self.executor.async_execute_command(
            OverkizCommand.SET_ON_OFF, OverkizCommandParam.ON
        )

    @override
    async def async_turn_off(self) -> None:
        """Turn the heater off."""
        await self.executor.async_execute_command(
            OverkizCommand.SET_ON_OFF, OverkizCommandParam.OFF
        )

    @property
    @override
    def preset_mode(self) -> str | None:
        """Return the current preset mode, e.g., home, away, temp."""
        if (
            state := self.device.states.get(
                OverkizState.MODBUSLINK_TARGET_HEATING_LEVEL
            )
        ) and state.value_as_str:
            return OVERKIZ_TO_PRESET_MODE.get(state.value_as_str)
        return None

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        await self.executor.async_execute_command(
            OverkizCommand.SET_HEATING_LEVEL, PRESET_MODE_TO_OVERKIZ[preset_mode]
        )

    @property
    @override
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        if (
            state := self.device.states.get(
                OverkizState.CORE_MAXIMUM_HEATING_TARGET_TEMPERATURE
            )
        ) and state.value_as_float is not None:
            return state.value_as_float
        return super().max_temp

    @property
    @override
    def native_target_temperature(self) -> float | None:
        """Return the temperature."""
        if state := self.device.states.get(OverkizState.CORE_TARGET_TEMPERATURE):
            return state.value_as_float
        return None

    @property
    @override
    def native_current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.temperature_device is not None and (
            temperature := self.temperature_device.states.get(
                OverkizState.CORE_TEMPERATURE
            )
        ):
            return temperature.value_as_float
        return None

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new temperature."""
        await self.executor.async_execute_command(
            OverkizCommand.SET_TARGET_TEMPERATURE, kwargs[ATTR_TEMPERATURE]
        )
