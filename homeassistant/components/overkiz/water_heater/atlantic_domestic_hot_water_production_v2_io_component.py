"""Support for AtlanticDomesticHotWaterProductionV2IOComponent."""

from typing import Any, cast

from pyoverkiz.enums import OverkizCommand, OverkizCommandParam, OverkizState
from pyoverkiz.models import Command

from homeassistant.components.water_heater import (
    STATE_ECO,
    STATE_ELECTRIC,
    STATE_HEAT_PUMP,
    STATE_PERFORMANCE,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature

from ..entity import OverkizEntity

DEFAULT_MIN_TEMP: float = 50.0
DEFAULT_MAX_TEMP: float = 62.0
MAX_BOOST_MODE_DURATION: int = 7

DHWP_AWAY_MODES = [
    OverkizCommandParam.ABSENCE,
    OverkizCommandParam.AWAY,
    OverkizCommandParam.FROSTPROTECTION,
]


class AtlanticDomesticHotWaterProductionV2IOComponent(OverkizEntity, WaterHeaterEntity):
    """Representation of AtlanticDomesticHotWaterProductionV2IOComponent (io)."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
        | WaterHeaterEntityFeature.AWAY_MODE
        | WaterHeaterEntityFeature.ON_OFF
    )
    _attr_operation_list = [
        STATE_ECO,
        STATE_PERFORMANCE,
        STATE_HEAT_PUMP,
        STATE_ELECTRIC,
    ]

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""

        min_temp = self.device.states.get(
            OverkizState.CORE_MINIMAL_TEMPERATURE_MANUAL_MODE
        )
        if min_temp:
            return min_temp.value_as_float or DEFAULT_MIN_TEMP
        return DEFAULT_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""

        max_temp = self.device.states.get(
            OverkizState.CORE_MAXIMAL_TEMPERATURE_MANUAL_MODE
        )
        if max_temp:
            return max_temp.value_as_float or DEFAULT_MAX_TEMP
        return DEFAULT_MAX_TEMP

    @property
    def current_temperature(self) -> float:
        """Return the current temperature."""

        return cast(
            float,
            self.device.states.get_value(
                OverkizState.IO_MIDDLE_WATER_TEMPERATURE,
            ),
        )

    @property
    def target_temperature(self) -> float:
        """Return the temperature corresponding to the PRESET."""

        return cast(
            float,
            self.device.states.get_value(OverkizState.CORE_TARGET_TEMPERATURE),
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new temperature."""

        temperature = kwargs[ATTR_TEMPERATURE]
        await self.executor.async_execute_commands(
            [
                Command(
                    name=OverkizCommand.SET_TARGET_TEMPERATURE,
                    parameters=[temperature],
                ),
                Command(name=OverkizCommand.REFRESH_TARGET_TEMPERATURE),
            ]
        )

    @property
    def is_state_eco(self) -> bool:
        """Return true if eco mode is on."""

        return (
            self.device.states.get_value(OverkizState.IO_DHW_MODE)
            == OverkizCommandParam.MANUAL_ECO_ACTIVE
        )

    @property
    def is_state_performance(self) -> bool:
        """Return true if performance mode is on."""

        return (
            self.device.states.get_value(OverkizState.IO_DHW_MODE)
            == OverkizCommandParam.AUTO_MODE
        )

    @property
    def is_state_heat_pump(self) -> bool:
        """Return true if heat pump mode is on."""

        return (
            self.device.states.get_value(OverkizState.IO_DHW_MODE)
            == OverkizCommandParam.MANUAL_ECO_INACTIVE
        )

    @property
    def is_away_mode_on(self) -> bool:
        """Return true if away mode is on."""

        away_mode_duration = cast(
            str, self.device.states.get_value(OverkizState.IO_AWAY_MODE_DURATION)
        )
        # away_mode_duration can be either a Literal["always"]
        if away_mode_duration == OverkizCommandParam.ALWAYS:
            return True

        # Or an int of 0 to 7 days. But it still is a string.
        if away_mode_duration.isdecimal() and int(away_mode_duration) > 0:
            return True

        return False

    @property
    def current_operation(self) -> str | None:
        """Return current operation."""

        # The Away Mode leaves the current operation unchanged
        if self.is_boost_mode_on:
            return STATE_ELECTRIC

        if self.is_state_eco:
            return STATE_ECO

        if self.is_state_performance:
            return STATE_PERFORMANCE

        if self.is_state_heat_pump:
            return STATE_HEAT_PUMP

        return None

    @property
    def is_boost_mode_on(self) -> bool:
        """Return true if boost mode is on."""

        return (
            cast(
                int,
                self.device.states.get_value(OverkizState.CORE_BOOST_MODE_DURATION),
            )
            > 0
        )

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        """Set new operation mode."""

        commands: list[Command] = []

        if operation_mode == STATE_ECO:
            if self.is_boost_mode_on:
                commands += self._boost_mode_off_commands()

            if self.is_away_mode_on:
                commands += self._away_mode_off_commands()

            commands.append(
                Command(
                    name=OverkizCommand.SET_DHW_MODE,
                    parameters=[OverkizCommandParam.MANUAL_ECO_ACTIVE],
                )
            )
            # ECO changes the target temperature so we have to refresh it
            commands.append(Command(name=OverkizCommand.REFRESH_TARGET_TEMPERATURE))

        elif operation_mode == STATE_PERFORMANCE:
            if self.is_boost_mode_on:
                commands += self._boost_mode_off_commands()
            if self.is_away_mode_on:
                commands += self._away_mode_off_commands()

            commands.append(
                Command(
                    name=OverkizCommand.SET_DHW_MODE,
                    parameters=[OverkizCommandParam.AUTO_MODE],
                )
            )

        elif operation_mode == STATE_HEAT_PUMP:
            refresh_target_temp = False
            if self.is_state_performance:
                # Switching from STATE_PERFORMANCE to
                # STATE_HEAT_PUMP changes the target temperature
                # and requires a target temperature refresh
                refresh_target_temp = True

            if self.is_boost_mode_on:
                commands += self._boost_mode_off_commands()
            if self.is_away_mode_on:
                commands += self._away_mode_off_commands()

            commands.append(
                Command(
                    name=OverkizCommand.SET_DHW_MODE,
                    parameters=[OverkizCommandParam.MANUAL_ECO_INACTIVE],
                )
            )

            if refresh_target_temp:
                commands.append(Command(name=OverkizCommand.REFRESH_TARGET_TEMPERATURE))

        elif operation_mode == STATE_ELECTRIC:
            if self.is_away_mode_on:
                commands += self._away_mode_off_commands()
            if not self.is_boost_mode_on:
                commands += self._boost_mode_on_commands()

        if commands:
            await self.executor.async_execute_commands(commands)

    async def async_turn_away_mode_on(self) -> None:
        """Turn away mode on."""

        await self.executor.async_execute_commands(self._away_mode_on_commands())

    async def async_turn_away_mode_off(self) -> None:
        """Turn away mode off."""

        await self.executor.async_execute_commands(self._away_mode_off_commands())

    def _away_mode_on_commands(self) -> list[Command]:
        """Commands to turn away mode on (and refresh away duration)."""

        return [
            Command(
                name=OverkizCommand.SET_CURRENT_OPERATING_MODE,
                parameters=[
                    {
                        OverkizCommandParam.RELAUNCH: OverkizCommandParam.OFF,
                        OverkizCommandParam.ABSENCE: OverkizCommandParam.ON,
                    }
                ],
            ),
            # Toggling the AWAY mode changes away mode duration so we have to refresh it
            Command(name=OverkizCommand.REFRESH_AWAY_MODE_DURATION),
        ]

    def _away_mode_off_commands(self) -> list[Command]:
        """Commands to turn away mode off (and refresh away duration)."""

        return [
            Command(
                name=OverkizCommand.SET_CURRENT_OPERATING_MODE,
                parameters=[
                    {
                        OverkizCommandParam.RELAUNCH: OverkizCommandParam.OFF,
                        OverkizCommandParam.ABSENCE: OverkizCommandParam.OFF,
                    }
                ],
            ),
            # Toggling the AWAY mode changes away mode duration so we have to refresh it
            Command(name=OverkizCommand.REFRESH_AWAY_MODE_DURATION),
        ]

    def _boost_mode_on_commands(self) -> list[Command]:
        """Commands to turn boost mode on (and refresh durations)."""

        commands = [
            Command(
                name=OverkizCommand.SET_BOOST_MODE_DURATION,
                parameters=[MAX_BOOST_MODE_DURATION],
            ),
            Command(
                name=OverkizCommand.SET_CURRENT_OPERATING_MODE,
                parameters=[
                    {
                        OverkizCommandParam.RELAUNCH: OverkizCommandParam.ON,
                        OverkizCommandParam.ABSENCE: OverkizCommandParam.OFF,
                    }
                ],
            ),
            Command(name=OverkizCommand.REFRESH_BOOST_MODE_DURATION),
        ]

        if self.is_state_performance:
            # Switching from STATE_PERFORMANCE to BOOST requires
            # a target temperature refresh
            commands.append(Command(name=OverkizCommand.REFRESH_TARGET_TEMPERATURE))

        return commands

    def _boost_mode_off_commands(self) -> list[Command]:
        """Commands to turn boost mode off (and refresh boost duration)."""

        return [
            Command(
                name=OverkizCommand.SET_CURRENT_OPERATING_MODE,
                parameters=[
                    {
                        OverkizCommandParam.RELAUNCH: OverkizCommandParam.OFF,
                        OverkizCommandParam.ABSENCE: OverkizCommandParam.OFF,
                    }
                ],
            ),
            # Toggling the BOOST mode changes boost mode duration so we have to refresh it
            Command(name=OverkizCommand.REFRESH_BOOST_MODE_DURATION),
        ]
