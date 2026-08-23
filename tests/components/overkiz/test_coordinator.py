"""Tests for the Overkiz data update coordinator."""

from unittest.mock import Mock, patch

from aiohttp import ClientConnectorError
from freezegun.api import FrozenDateTimeFactory
from pyoverkiz.exceptions import (
    InvalidEventListenerIdError,
    MaintenanceError,
    ServiceUnavailableError,
    TooManyConcurrentRequestsError,
    TooManyRequestsError,
)
import pytest

from homeassistant.components.overkiz.const import DOMAIN, UPDATE_INTERVAL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .conftest import FixtureDevice, MockOverkizClient, SetupOverkizIntegration
from .helpers import async_deliver_events, device_created_event, device_removed_event

from tests.common import MockConfigEntry, async_fire_time_changed

TEMPERATURE_SENSOR = FixtureDevice(
    "setup/cloud_nexity_rail_din_europe.json",
    "io://1234-5678-1698/15702199#2",
    "sensor.maple_residence_bathroom_temperature_sensor_temperature",
)

# A radiator and a temperature sensor that are sub devices of one physical device,
# next to a smoke detector that is a physical device on its own.
PHYSICAL_DEVICE_URL = "io://1234-5678-1698/15702199"
RADIATOR_URL = f"{PHYSICAL_DEVICE_URL}#1"
TEMPERATURE_SENSOR_URL = f"{PHYSICAL_DEVICE_URL}#2"
SMOKE_DETECTOR_URL = "io://1234-5678-1698/8907539"

# A TaHoma v2 setup whose gateways list only holds the main box, while a
# swinging gate device is hosted by a secondary box absent from setup.gateways.
TAHOMA_V2_FIXTURE = "setup/cloud_somfy_tahoma_v2_europe.json"
MAIN_GATEWAY_ID = "1234-1234-6233"
SECONDARY_GATEWAY_ID = "1234-1234-8983"
MAIN_GATEWAY_DEVICE_URL = "io://1234-1234-6233/12184029"
SECONDARY_GATEWAY_DEVICE_URL = "io://1234-1234-8983/1959462"


@pytest.mark.parametrize(
    "exception",
    [
        TooManyConcurrentRequestsError("Too many concurrent requests"),
        TooManyRequestsError("Too many requests"),
        MaintenanceError("Server is down for maintenance"),
        ServiceUnavailableError("Server is unavailable"),
        InvalidEventListenerIdError("Invalid event listener id"),
        TimeoutError("Timed out"),
        ClientConnectorError(Mock(), Mock()),
    ],
    ids=[
        "too_many_concurrent_requests",
        "too_many_requests",
        "maintenance",
        "service_unavailable",
        "invalid_event_listener_id",
        "timeout",
        "client_connector_error",
    ],
)
async def test_transient_error_is_retried(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    exception: Exception,
) -> None:
    """Transient errors are handled cleanly: entities go unavailable, then recover."""
    await setup_overkiz_integration(fixture=TEMPERATURE_SENSOR.fixture)

    initial_state = hass.states.get(TEMPERATURE_SENSOR.entity_id)
    assert initial_state.state != STATE_UNAVAILABLE

    # A transient error during a refresh makes the entities unavailable.
    mock_client.fetch_events.side_effect = exception
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(TEMPERATURE_SENSOR.entity_id).state == STATE_UNAVAILABLE

    # Once the server recovers, the next refresh restores the entities.
    mock_client.fetch_events.side_effect = None
    mock_client.fetch_events.return_value = []
    freezer.tick(UPDATE_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get(TEMPERATURE_SENSOR.entity_id).state == initial_state.state


async def test_device_removed_deletes_device(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A DEVICE_REMOVED event deletes a device owned only by this config entry."""
    config_entry = await setup_overkiz_integration(fixture=TEMPERATURE_SENSOR.fixture)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SMOKE_DETECTOR_URL), config_entry.entry_id
    )
    assert device is not None

    await async_deliver_events(
        hass, freezer, mock_client, [device_removed_event(SMOKE_DETECTOR_URL)]
    )

    assert device_registry.async_get(device.id) is None


async def test_sub_device_removed_deletes_child_device(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A DEVICE_REMOVED event of a sub device only deletes its child device."""
    config_entry = await setup_overkiz_integration(fixture=TEMPERATURE_SENSOR.fixture)

    child_device = device_registry.async_get_child_device_by_identifier(
        (DOMAIN, TEMPERATURE_SENSOR_URL), config_entry.entry_id
    )
    assert child_device is not None

    await async_deliver_events(
        hass, freezer, mock_client, [device_removed_event(TEMPERATURE_SENSOR_URL)]
    )

    assert device_registry.async_get(child_device.id) is None
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, PHYSICAL_DEVICE_URL), config_entry.entry_id
        )
        is not None
    )


async def test_device_removed_deletes_child_devices(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A DEVICE_REMOVED event of a main device deletes its child devices as well."""
    config_entry = await setup_overkiz_integration(fixture=TEMPERATURE_SENSOR.fixture)

    child_device = device_registry.async_get_child_device_by_identifier(
        (DOMAIN, TEMPERATURE_SENSOR_URL), config_entry.entry_id
    )
    assert child_device is not None

    await async_deliver_events(
        hass, freezer, mock_client, [device_removed_event(RADIATOR_URL)]
    )

    assert device_registry.async_get(child_device.id) is None
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, PHYSICAL_DEVICE_URL), config_entry.entry_id
        )
        is None
    )


async def test_device_removed_keeps_device_owned_by_other_entry(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
) -> None:
    """A DEVICE_REMOVED event does not delete a device owned by another entry."""
    config_entry = await setup_overkiz_integration(fixture=TEMPERATURE_SENSOR.fixture)

    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SMOKE_DETECTOR_URL), config_entry.entry_id
    )
    assert device is not None

    # Move the device to another config entry; removing the Overkiz entry must then
    # leave it in place instead of deleting a device it no longer owns.
    other_entry = MockConfigEntry(domain="other")
    other_entry.add_to_hass(hass)
    device_registry.async_update_device(
        device.id, new_config_entry_id=other_entry.entry_id
    )

    await async_deliver_events(
        hass, freezer, mock_client, [device_removed_event(SMOKE_DETECTOR_URL)]
    )

    device = device_registry.async_get(device.id)
    assert device is not None
    assert device.config_entry_id == other_entry.entry_id


async def test_devices_link_to_their_gateway(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Every device links to its gateway, even one absent from setup.gateways.

    The secondary box that hosts the swinging gate is not returned in
    setup.gateways, but the via_device link of its devices must still resolve.
    A DEVICE_CREATED event reloads the entry, which must keep the link intact.
    """
    mock_config_entry.add_to_hass(hass)
    mock_client.set_setup_fixture(TAHOMA_V2_FIXTURE)

    with patch(
        "homeassistant.components.overkiz.create_cloud_client",
        return_value=mock_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        main_gateway = device_registry.async_get_device_by_identifier(
            (DOMAIN, MAIN_GATEWAY_ID), mock_config_entry.entry_id
        )
        secondary_gateway = device_registry.async_get_device_by_identifier(
            (DOMAIN, SECONDARY_GATEWAY_ID), mock_config_entry.entry_id
        )
        assert main_gateway is not None
        assert secondary_gateway is not None

        main_gateway_device = device_registry.async_get_device_by_identifier(
            (DOMAIN, MAIN_GATEWAY_DEVICE_URL), mock_config_entry.entry_id
        )
        secondary_gateway_device = device_registry.async_get_device_by_identifier(
            (DOMAIN, SECONDARY_GATEWAY_DEVICE_URL), mock_config_entry.entry_id
        )
        assert main_gateway_device is not None
        assert secondary_gateway_device is not None
        assert main_gateway_device.via_device_id == main_gateway.id
        assert secondary_gateway_device.via_device_id == secondary_gateway.id

        # A DEVICE_CREATED event reloads the entry; the links must survive.
        await async_deliver_events(
            hass,
            freezer,
            mock_client,
            [device_created_event(SECONDARY_GATEWAY_DEVICE_URL)],
        )

    assert mock_config_entry.state is ConfigEntryState.LOADED

    secondary_gateway = device_registry.async_get_device_by_identifier(
        (DOMAIN, SECONDARY_GATEWAY_ID), mock_config_entry.entry_id
    )
    secondary_gateway_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, SECONDARY_GATEWAY_DEVICE_URL), mock_config_entry.entry_id
    )
    assert secondary_gateway is not None
    assert secondary_gateway_device is not None
    assert secondary_gateway_device.via_device_id == secondary_gateway.id
