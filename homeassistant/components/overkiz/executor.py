"""Class for helpers and communication with the OverKiz API."""

from typing import Any

from pyoverkiz.enums import OverkizCommand
from pyoverkiz.exceptions import BaseOverkizError
from pyoverkiz.models import Action, Command, Device

from homeassistant.exceptions import HomeAssistantError

from .coordinator import OverkizDataUpdateCoordinator


class OverkizExecutor:
    """Representation of an Overkiz device with execution handler."""

    def __init__(
        self, device_url: str, coordinator: OverkizDataUpdateCoordinator
    ) -> None:
        """Initialize the executor."""
        self.device_url = device_url
        self.coordinator = coordinator

    @property
    def device(self) -> Device:
        """Return Overkiz device linked to this entity."""
        return self.coordinator.data[self.device_url]

    def linked_device(self, index: int) -> Device | None:
        """Return Overkiz device sharing the same base url."""
        return self.coordinator.data.get(
            f"{self.device.identifier.base_device_url}#{index}"
        )

    async def async_execute_command(
        self,
        command_name: str | OverkizCommand,
        parameters: list[Any] | None = None,
    ) -> None:
        """Execute a single device command as one action group, then refresh."""
        await self.async_execute_commands(
            [Command(name=command_name, parameters=parameters)]
        )

    async def async_execute_commands(self, commands: list[Command]) -> None:
        """Execute multiple commands on this device as one action group.

        All commands are sent as a single execution, so the device is polled
        once rather than once per command. State is refreshed afterwards.
        """
        try:
            exec_id = await self.coordinator.client.execute_action_group(
                label="Home Assistant",
                actions=[Action(device_url=self.device.device_url, commands=commands)],
            )
        # Catch Overkiz exceptions to support `continue_on_error` functionality
        except BaseOverkizError as exception:
            raise HomeAssistantError(exception) from exception

        # ExecutionRegisteredEvent doesn't contain the device_url, thus we need
        # to register it here. The action queue can return the same exec_id for
        # several merged action groups, so accumulate rather than overwrite.
        self.coordinator.executions.setdefault(exec_id, []).extend(
            {
                "device_url": self.device.device_url,
                "command_name": str(command.name),
            }
            for command in commands
        )

        await self.coordinator.async_refresh()

    async def async_cancel_command(
        self, commands_to_cancel: list[OverkizCommand]
    ) -> bool:
        """Cancel running execution by command."""

        # Cancel a running execution. Retrieve executions
        # initiated via Home Assistant from Data Update
        # Coordinator queue
        exec_id = next(
            (
                exec_id
                # Reverse dictionary to cancel the last added execution
                for exec_id, executions in reversed(self.coordinator.executions.items())
                for execution in executions
                if execution["device_url"] == self.device.device_url
                and execution["command_name"] in commands_to_cancel
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
