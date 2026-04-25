"""Class for helpers and communication with the OverKiz API."""

from __future__ import annotations

from typing import Any

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
            "command_names": [command.name for command in commands],
        }
        if refresh_afterwards:
            await self.coordinator.async_refresh()
