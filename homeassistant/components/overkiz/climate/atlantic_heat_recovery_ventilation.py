"""Support for AtlanticHeatRecoveryVentilation."""

from typing import cast

from pyoverkiz.enums import OverkizCommand, OverkizCommandParam, OverkizState
from pyoverkiz.models import Command

from homeassistant.components.climate import (
    FAN_AUTO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature

from ..const import DOMAIN
from ..coordinator import OverkizDataUpdateCoordinator
from ..entity import OverkizEntity

FAN_BOOST = "home_boost"
FAN_KITCHEN = "kitchen_boost"
FAN_AWAY = "away"
FAN_BYPASS = "bypass_boost"

PRESET_AUTO = "auto"
PRESET_PROG = "prog"
PRESET_MANUAL = "manual"

OVERKIZ_TO_FAN_MODES: dict[str, str] = {
    OverkizCommandParam.AUTO: FAN_AUTO,
    OverkizCommandParam.AWAY: FAN_AWAY,
    OverkizCommandParam.BOOST: FAN_BOOST,
    OverkizCommandParam.HIGH: FAN_KITCHEN,
    "": FAN_BYPASS,
}

FAN_MODES_TO_OVERKIZ = {v: k for k, v in OVERKIZ_TO_FAN_MODES.items()}

TEMPERATURE_SENSOR_DEVICE_INDEX = 4


class AtlanticHeatRecoveryVentilation(OverkizEntity, ClimateEntity):
    """Representation of a AtlanticHeatRecoveryVentilation device."""

    _attr_fan_modes = [*FAN_MODES_TO_OVERKIZ]
    _attr_hvac_mode = HVACMode.FAN_ONLY
    _attr_hvac_modes = [HVACMode.FAN_ONLY]
    _attr_preset_modes = [PRESET_AUTO, PRESET_PROG, PRESET_MANUAL]
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.FAN_MODE
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
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        if self.temperature_device is not None and (
            temperature := self.temperature_device.states.get(
                OverkizState.CORE_TEMPERATURE
            )
        ):
            return temperature.value_as_float

        return None

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        """Not implemented since there is only one hvac_mode."""

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        ventilation_configuration = self.device.states.get_value(
            OverkizState.IO_VENTILATION_CONFIGURATION_MODE
        )

        if ventilation_configuration == OverkizCommandParam.COMFORT:
            return PRESET_AUTO

        if ventilation_configuration == OverkizCommandParam.STANDARD:
            return PRESET_MANUAL

        ventilation_mode = cast(
            dict, self.device.states.get_value(OverkizState.IO_VENTILATION_MODE)
        )
        prog = ventilation_mode.get(OverkizCommandParam.PROG)

        if prog == OverkizCommandParam.ON:
            return PRESET_PROG

        return None

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        commands: list[Command] = []

        if preset_mode == PRESET_AUTO:
            commands.append(
                Command(
                    name=OverkizCommand.SET_VENTILATION_CONFIGURATION_MODE,
                    parameters=[OverkizCommandParam.COMFORT],
                )
            )
            commands.append(
                self._ventilation_mode_command(prog=OverkizCommandParam.OFF)
            )

        if preset_mode == PRESET_PROG:
            commands.append(
                Command(
                    name=OverkizCommand.SET_VENTILATION_CONFIGURATION_MODE,
                    parameters=[OverkizCommandParam.STANDARD],
                )
            )
            commands.append(self._ventilation_mode_command(prog=OverkizCommandParam.ON))

        if preset_mode == PRESET_MANUAL:
            commands.append(
                Command(
                    name=OverkizCommand.SET_VENTILATION_CONFIGURATION_MODE,
                    parameters=[OverkizCommandParam.STANDARD],
                )
            )
            commands.append(
                self._ventilation_mode_command(prog=OverkizCommandParam.OFF)
            )

        commands.append(Command(name=OverkizCommand.REFRESH_VENTILATION_STATE))
        commands.append(
            Command(name=OverkizCommand.REFRESH_VENTILATION_CONFIGURATION_MODE)
        )

        await self.executor.async_execute_commands(commands)

    @property
    def fan_mode(self) -> str | None:
        """Return the fan setting."""
        ventilation_mode = cast(
            dict, self.device.states.get_value(OverkizState.IO_VENTILATION_MODE)
        )
        cooling = ventilation_mode.get(OverkizCommandParam.COOLING)

        if cooling == OverkizCommandParam.ON:
            return FAN_BYPASS

        return OVERKIZ_TO_FAN_MODES[
            cast(str, self.device.states.get_value(OverkizState.IO_AIR_DEMAND_MODE))
        ]

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set new target fan mode."""
        if fan_mode == FAN_BYPASS:
            commands = [
                Command(
                    name=OverkizCommand.SET_AIR_DEMAND_MODE,
                    parameters=[OverkizCommandParam.AUTO],
                ),
                self._ventilation_mode_command(cooling=OverkizCommandParam.ON),
            ]
        else:
            commands = [
                self._ventilation_mode_command(cooling=OverkizCommandParam.OFF),
                Command(
                    name=OverkizCommand.SET_AIR_DEMAND_MODE,
                    parameters=[FAN_MODES_TO_OVERKIZ[fan_mode]],
                ),
            ]

        commands.append(Command(name=OverkizCommand.REFRESH_VENTILATION_STATE))

        await self.executor.async_execute_commands(commands)

    def _ventilation_mode_command(
        self,
        cooling: str | None = None,
        prog: str | None = None,
    ) -> Command:
        """Build the ventilation mode command with all parameters."""
        ventilation_mode = cast(
            dict, self.device.states.get_value(OverkizState.IO_VENTILATION_MODE)
        )

        if cooling:
            ventilation_mode[OverkizCommandParam.COOLING] = cooling

        if prog:
            ventilation_mode[OverkizCommandParam.PROG] = prog

        return Command(
            name=OverkizCommand.SET_VENTILATION_MODE, parameters=[ventilation_mode]
        )
