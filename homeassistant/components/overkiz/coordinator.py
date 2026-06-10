"""Helpers to help coordinate updates."""

import asyncio
from collections.abc import Callable, Coroutine
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import ClientConnectorError, ServerDisconnectedError
from pyoverkiz.client import OverkizClient
from pyoverkiz.enums import EventName, ExecutionState
from pyoverkiz.exceptions import (
    BadCredentialsError,
    InvalidEventListenerIdError,
    MaintenanceError,
    NotAuthenticatedError,
    ServiceUnavailableError,
    TooManyConcurrentRequestsError,
    TooManyRequestsError,
)
from pyoverkiz.models import (
    Device,
    DeviceEvent,
    DeviceRemovedEvent,
    DeviceStateChangedEvent,
    ExecutionRegisteredEvent,
    ExecutionStateChangedEvent,
    Place,
)

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.decorator import Registry

if TYPE_CHECKING:
    from . import OverkizDataConfigEntry

from .const import (
    DOMAIN,
    IGNORED_OVERKIZ_DEVICES,
    LOGGER,
    STATELESS_PROTOCOLS,
    UPDATE_INTERVAL,
)

# Events are a discriminated union; each handler narrows to its own subtype.
EVENT_HANDLERS: Registry[
    str, Callable[[OverkizDataUpdateCoordinator, Any], Coroutine[Any, Any, None]]
] = Registry()


class OverkizDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Device]]):
    """Class to manage fetching data from Overkiz platform."""

    config_entry: OverkizDataConfigEntry
    _default_update_interval: timedelta

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: OverkizDataConfigEntry,
        logger: logging.Logger,
        *,
        client: OverkizClient,
        devices: list[Device],
        places: Place | None,
    ) -> None:
        """Initialize global data updater."""
        super().__init__(
            hass,
            logger,
            config_entry=config_entry,
            name="device events",
            update_interval=UPDATE_INTERVAL,
        )

        self.data = {}
        self.client = client
        self.devices: dict[str, Device] = {d.device_url: d for d in devices}
        self.executions: dict[str, dict[str, str]] = {}
        # Futures resolved once a command's result arrives (IN_PROGRESS or a
        # terminal state). Keyed by execution id.
        self.execution_results: dict[str, asyncio.Future[None]] = {}
        self.areas = self._places_to_area(places) if places else None
        self._default_update_interval = UPDATE_INTERVAL

        self.is_stateless = all(
            device.identifier.protocol in STATELESS_PROTOCOLS
            for device in devices
            if device.widget not in IGNORED_OVERKIZ_DEVICES
            and device.ui_class not in IGNORED_OVERKIZ_DEVICES
        )

    async def _async_update_data(self) -> dict[str, Device]:
        """Fetch Overkiz data via event listener."""
        try:
            events = await self.client.fetch_events()
        except (BadCredentialsError, NotAuthenticatedError) as exception:
            raise ConfigEntryAuthFailed("Invalid authentication.") from exception
        except TooManyConcurrentRequestsError as exception:
            raise UpdateFailed("Too many concurrent requests.") from exception
        except TooManyRequestsError as exception:
            raise UpdateFailed("Too many requests, try again later.") from exception
        except MaintenanceError as exception:
            raise UpdateFailed("Server is down for maintenance.") from exception
        except ServiceUnavailableError as exception:
            raise UpdateFailed("Server is unavailable.") from exception
        except InvalidEventListenerIdError as exception:
            raise UpdateFailed(exception) from exception
        except (TimeoutError, ClientConnectorError) as exception:
            LOGGER.debug("Failed to connect", exc_info=True)
            raise UpdateFailed("Failed to connect.") from exception
        except ServerDisconnectedError:
            self.executions = {}
            self._resolve_pending_results()

            # During the relogin, similar exceptions can be thrown.
            try:
                await self.client.login()
                self.devices = await self._get_devices()
            except (BadCredentialsError, NotAuthenticatedError) as exception:
                raise ConfigEntryAuthFailed("Invalid authentication.") from exception
            except TooManyRequestsError as exception:
                raise UpdateFailed("Too many requests, try again later.") from exception

            return self.devices

        for event in events:
            LOGGER.debug(event)

            if event_handler := EVENT_HANDLERS.get(event.name):
                await event_handler(self, event)

        # Restore the default update interval if no executions are pending
        if not self.executions:
            self.update_interval = self._default_update_interval

        return self.devices

    async def _get_devices(self) -> dict[str, Device]:
        """Fetch devices."""
        LOGGER.debug("Fetching all devices and state via /setup/devices")
        return {d.device_url: d for d in await self.client.get_devices(refresh=True)}

    def _places_to_area(self, place: Place) -> dict[str, str]:
        """Convert places with sub_places to a flat dictionary [placeoid, label])."""
        areas = {}
        if isinstance(place, Place):
            areas[place.oid] = place.label

        if isinstance(place.sub_places, list):
            for sub_place in place.sub_places:
                areas.update(self._places_to_area(sub_place))

        return areas

    def set_update_interval(self, update_interval: timedelta) -> None:
        """Set the update interval and store this value."""
        self.update_interval = update_interval
        self._default_update_interval = update_interval

    def register_execution_result(self, exec_id: str) -> asyncio.Future[None]:
        """Register a future that resolves when an execution result arrives."""
        future = self.hass.loop.create_future()
        self.execution_results[exec_id] = future
        return future

    def _resolve_pending_results(self) -> None:
        """Resolve all pending execution results, e.g. after a reconnect.

        Without a connection we can no longer correlate execution events, so we
        resolve callers optimistically instead of leaving them to time out.
        """
        for future in self.execution_results.values():
            if not future.done():
                future.set_result(None)
        self.execution_results.clear()


@EVENT_HANDLERS.register(EventName.DEVICE_AVAILABLE)
async def on_device_available(
    coordinator: OverkizDataUpdateCoordinator, event: DeviceEvent
) -> None:
    """Handle device available event."""
    if event.device_url in coordinator.devices:
        coordinator.devices[event.device_url].available = True


@EVENT_HANDLERS.register(EventName.DEVICE_UNAVAILABLE)
@EVENT_HANDLERS.register(EventName.DEVICE_DISABLED)
async def on_device_unavailable_disabled(
    coordinator: OverkizDataUpdateCoordinator, event: DeviceEvent
) -> None:
    """Handle device unavailable / disabled event."""
    if event.device_url in coordinator.devices:
        coordinator.devices[event.device_url].available = False


@EVENT_HANDLERS.register(EventName.DEVICE_CREATED)
@EVENT_HANDLERS.register(EventName.DEVICE_UPDATED)
async def on_device_created_updated(
    coordinator: OverkizDataUpdateCoordinator, event: DeviceEvent
) -> None:
    """Handle device unavailable / disabled event."""
    coordinator.hass.async_create_task(
        coordinator.hass.config_entries.async_reload(coordinator.config_entry.entry_id)
    )


@EVENT_HANDLERS.register(EventName.DEVICE_STATE_CHANGED)
async def on_device_state_changed(
    coordinator: OverkizDataUpdateCoordinator, event: DeviceStateChangedEvent
) -> None:
    """Handle device state changed event."""
    if event.device_url not in coordinator.devices:
        return

    for state in event.device_states:
        device = coordinator.devices[event.device_url]
        device.states[state.name] = state


@EVENT_HANDLERS.register(EventName.DEVICE_REMOVED)
async def on_device_removed(
    coordinator: OverkizDataUpdateCoordinator, event: DeviceRemovedEvent
) -> None:
    """Handle device removed event."""
    base_device_url = event.device_url.split("#")[0]
    registry = dr.async_get(coordinator.hass)

    if registered_device := registry.async_get_device(
        identifiers={(DOMAIN, base_device_url)}
    ):
        registry.async_remove_device(registered_device.id)

    if event.device_url in coordinator.devices:
        del coordinator.devices[event.device_url]


@EVENT_HANDLERS.register(EventName.EXECUTION_REGISTERED)
async def on_execution_registered(
    coordinator: OverkizDataUpdateCoordinator, event: ExecutionRegisteredEvent
) -> None:
    """Handle execution registered event."""
    if event.exec_id not in coordinator.executions:
        coordinator.executions[event.exec_id] = {}

    if not coordinator.is_stateless:
        coordinator.update_interval = timedelta(seconds=1)


@EVENT_HANDLERS.register(EventName.EXECUTION_STATE_CHANGED)
async def on_execution_state_changed(
    coordinator: OverkizDataUpdateCoordinator, event: ExecutionStateChangedEvent
) -> None:
    """Handle execution changed event.

    The gateway reports a command's result by reaching IN_PROGRESS or, on
    rejection, FAILED. We resolve the caller's future at that point so the
    service call returns quickly, instead of waiting for the COMPLETED event
    which only fires once the physical movement has finished.
    """
    if event.exec_id not in coordinator.executions:
        return

    # IN_PROGRESS (or COMPLETED) means accepted; an early FAILED is a rejection
    # we surface to the caller. Any other state isn't a result yet, so keep
    # waiting for one.
    result = coordinator.execution_results.pop(event.exec_id, None)
    if result is not None and not result.done():
        if event.new_state is ExecutionState.FAILED:
            result.set_exception(
                HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="command_failed",
                    translation_placeholders={
                        "failure_type": event.failure_type or "unknown"
                    },
                )
            )
        elif event.new_state in (
            ExecutionState.IN_PROGRESS,
            ExecutionState.COMPLETED,
        ):
            result.set_result(None)
        else:
            coordinator.execution_results[event.exec_id] = result

    if event.new_state is ExecutionState.FAILED:
        execution = coordinator.executions[event.exec_id]
        LOGGER.warning(
            "Command %s failed for %s: %s",
            execution.get("command_name"),
            execution.get("device_url"),
            event.failure_type,
        )

    # Keep the execution tracked while it runs so cover entities can derive
    # their opening/closing state; drop it only once it terminates.
    if event.new_state in (ExecutionState.COMPLETED, ExecutionState.FAILED):
        del coordinator.executions[event.exec_id]
