"""Class for helpers and communication with the OverKiz API."""

from __future__ import annotations

from typing import Any

from pyoverkiz.enums import OverkizCommand, Protocol
from pyoverkiz.exceptions import BaseOverkizError
from pyoverkiz.models import Action, Command, Device, StateDefinition
from pyoverkiz.types import StateType as OverkizStateType

from homeassistant.exceptions import HomeAssistantError

from .coordinator import OverkizDataUpdateCoordinator

# Commands that don't support setting
# the delay to another value
COMMANDS_WITHOUT_DELAY = [
    OverkizCommand.IDENTIFY,
    OverkizCommand.OFF,
    OverkizCommand.ON,
    OverkizCommand.ON_WITH_TIMER,
    OverkizCommand.TEST,
]


class OverkizExecutor:
    """Representation of an Overkiz device with execution handler."""

    def __init__(
        self, device_url: str, coordinator: OverkizDataUpdateCoordinator
    ) -> None:
        """Initialize the executor."""
        self.device_url = device_url
        self.coordinator = coordinator

    @property
    def base_device_url(self) -> str:
        """Return the base device URL without subsystem id."""
        return self.device.identifier.base_device_url

    @property
    def device(self) -> Device:
        """Return Overkiz device linked to this entity."""
        return self.coordinator.data[self.device_url]

    def linked_device(self, index: int) -> Device | None:
        """Return Overkiz device sharing the same base url."""
        return self.coordinator.data.get(
            f"{self.device.identifier.base_device_url}#{index}"
        )

    def select_command(self, *commands: str) -> str | None:
        """Select first existing command in a list of commands."""
        return self.device.select_first_command(list(commands))

    def has_command(self, *commands: str) -> bool:
        """Return True if a command exists in a list of commands."""
        return self.device.supports_any_command(list(commands))

    def select_definition_state(self, *states: str) -> StateDefinition | None:
        """Select first existing definition state in a list of states."""
        return self.device.select_first_state_definition(list(states))

    def select_state(self, *states: str) -> OverkizStateType:
        """Select first existing active state in a list of states."""
        return self.device.select_first_state_value(list(states))

    def has_state(self, *states: str) -> bool:
        """Return True if a state exists in self."""
        return self.device.has_any_state_value(list(states))

    def select_attribute(self, *attributes: str) -> OverkizStateType:
        """Select first existing active state in a list of states."""
        return self.device.select_first_attribute_value(list(attributes))

    def get_gateway_id(self) -> str:
        """Retrieve gateway id from device url.

        device URL (<protocol>://<gatewayId>/<deviceAddress>[#<subsystemId>])
        """
        return self.device.identifier.gateway_id

    async def async_execute_command(
        self,
        command_name: str,
        args: list[Any] | None = None,
        *,
        refresh_afterwards: bool = True,
    ) -> None:
        """Execute device command in async context."""
        await self.async_execute_commands(
            [Command(name=command_name, parameters=args or [])],
            refresh_afterwards=refresh_afterwards,
        )

    async def async_execute_commands(
        self,
        commands: list[Command],
        *,
        refresh_afterwards: bool = True,
    ) -> None:
        """Execute multiple device commands in a single action group.

        :param refresh_afterwards: Whether to refresh the device state after the commands are executed.
        """
        # Set the execution duration to 0 seconds for RTS devices on supported commands
        # Default execution duration is 30 seconds and will block consecutive commands
        if self.device.identifier.protocol == Protocol.RTS:
            for command in commands:
                if command.name not in COMMANDS_WITHOUT_DELAY:
                    command.parameters = [*(command.parameters or []), 0]

        try:
            exec_id = await self.coordinator.client.execute_action_group(
                actions=[
                    Action(
                        device_url=self.device.device_url,
                        commands=commands,
                    )
                ],
                label="Home Assistant",
            )
        # Catch Overkiz exceptions to support `continue_on_error` functionality
        except BaseOverkizError as exception:
            raise HomeAssistantError(exception) from exception

        # ExecutionRegisteredEvent doesn't contain the device_url, thus we need to register it here
        self.coordinator.executions[exec_id] = {
            "device_url": self.device.device_url,
            "command_name": commands[0].name,
        }
        if refresh_afterwards:
            await self.coordinator.async_refresh()

    async def async_cancel_command(
        self, commands_to_cancel: list[OverkizCommand]
    ) -> bool:
        """Cancel running execution by command."""

        # Cancel a running execution
        # Retrieve executions initiated via Home Assistant from Data Update Coordinator queue
        exec_id = next(
            (
                exec_id
                # Reverse dictionary to cancel the last added execution
                for exec_id, execution in reversed(self.coordinator.executions.items())
                if execution.get("device_url") == self.device.device_url
                and execution.get("command_name") in commands_to_cancel
            ),
            None,
        )

        if exec_id:
            await self.async_cancel_execution(exec_id)
            return True

        # Retrieve executions initiated outside Home Assistant via API
        executions = await self.coordinator.client.get_current_executions()
        exec_id = next(
            (
                execution.id
                for execution in executions
                if execution.action_group
                for action in reversed(execution.action_group.actions)
                for command in action.commands
                if action.device_url == self.device.device_url
                and command.name in commands_to_cancel
            ),
            None,
        )

        if exec_id:
            await self.async_cancel_execution(exec_id)
            return True

        return False

    async def async_cancel_execution(self, exec_id: str) -> None:
        """Cancel running execution via execution id."""
        await self.coordinator.client.cancel_execution(exec_id)
