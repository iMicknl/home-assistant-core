"""Helpers to help coordinate updates."""

from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from aiohttp import ClientConnectorError, ServerDisconnectedError
from pyoverkiz.client import OverkizClient
from pyoverkiz.enums import ExecutionState, Protocol
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
    DeviceAvailableEvent,
    DeviceCreatedEvent,
    DeviceDisabledEvent,
    DeviceRemovedEvent,
    DeviceStateChangedEvent,
    DeviceUnavailableEvent,
    DeviceUpdatedEvent,
    Event,
    ExecutionRegisteredEvent,
    ExecutionStateChangedEvent,
    Place,
)

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

if TYPE_CHECKING:
    from . import OverkizDataConfigEntry

from .const import DOMAIN, IGNORED_OVERKIZ_DEVICES, LOGGER, UPDATE_INTERVAL


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
        self.executions: dict[str, list[dict[str, str]]] = {}
        self.areas = self._places_to_area(places) if places else None
        self._default_update_interval = UPDATE_INTERVAL

        self.is_stateless = all(
            device.identifier.protocol in (Protocol.RTS, Protocol.INTERNAL)
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
            self._handle_event(event)

        # Restore the default update interval if no executions are pending
        if not self.executions:
            self.update_interval = self._default_update_interval

        return self.devices

    def _handle_event(self, event: Event) -> None:
        """Apply a single event to the cached device state.

        As of pyoverkiz 2.0 events are a discriminated union keyed on their
        name, so each branch receives a precisely-typed event and the fields it
        accesses are guaranteed to be present.
        """
        match event:
            case DeviceAvailableEvent():
                if device := self.devices.get(event.device_url):
                    device.available = True
            case DeviceUnavailableEvent() | DeviceDisabledEvent():
                if device := self.devices.get(event.device_url):
                    device.available = False
            case DeviceCreatedEvent() | DeviceUpdatedEvent():
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(self.config_entry.entry_id)
                )
            case DeviceStateChangedEvent():
                if device := self.devices.get(event.device_url):
                    for state in event.device_states:
                        device.states[state.name] = state
            case DeviceRemovedEvent():
                self._remove_device(event)
            case ExecutionRegisteredEvent():
                if event.exec_id not in self.executions:
                    self.executions[event.exec_id] = []
                if not self.is_stateless:
                    self.update_interval = timedelta(seconds=1)
            case ExecutionStateChangedEvent():
                if event.exec_id in self.executions and event.new_state in (
                    ExecutionState.COMPLETED,
                    ExecutionState.FAILED,
                ):
                    del self.executions[event.exec_id]

    def _remove_device(self, event: DeviceRemovedEvent) -> None:
        """Remove a device from the registry and the cached device state."""
        device = self.devices.get(event.device_url)
        if device is None:
            return

        registry = dr.async_get(self.hass)
        if registered_device := registry.async_get_device(
            identifiers={(DOMAIN, device.identifier.base_device_url)}
        ):
            registry.async_remove_device(registered_device.id)

        del self.devices[event.device_url]

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
