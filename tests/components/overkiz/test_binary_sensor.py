"""Tests for the Overkiz binary sensor platform."""

from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

from attrs import evolve
from freezegun.api import FrozenDateTimeFactory
from pyoverkiz.enums import APIType, EventName, OverkizState, UpdateBoxStatus
from pyoverkiz.exceptions import BadCredentialsError, MaintenanceError
from pyoverkiz.models import (
    GatewayFirmwareUpdateCompletedEvent,
    GatewayFirmwareUpdatedEvent,
)
import pytest
from pytest_homeassistant.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.overkiz.const import DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import FixtureDevice, MockOverkizClient, SetupOverkizIntegration
from .helpers import (
    async_deliver_events,
    async_poll_gateway_update_status,
    device_state_changed_event,
    device_unavailable_event,
)

SMOKE_SENSOR = FixtureDevice(
    "setup/cloud_nexity_rail_din_europe.json",
    "io://1234-5678-1698/8907539",
    "binary_sensor.maple_residence_living_room_smoke_detector_smoke",
)
HEATING_STATUS = FixtureDevice(
    "setup/cloud_atlantic_cozytouch.json",
    "io://1234-5678-5643/109286#1",
    "binary_sensor.my_home_patio_water_heating_heating_status",
)
CONTACT_SENSOR = FixtureDevice(
    "setup/cloud_somfy_tahoma_v2_europe.json",
    "rtds://1234-1234-6233/394781",
    "binary_sensor.family_wing_porte_contact",
)
# Somfy IntelliTAG air tilt sensor (io:SomfyWindowStateSensor)
TILT_SENSOR = FixtureDevice(
    "setup/cloud_somfy_tahoma_v2_europe.json",
    "io://1234-1234-6233/8059108#1",
    "binary_sensor.living_room_balcony_window_tilt",
)
GATEWAY_FIXTURE = "setup/cloud_somfy_tahoma_v2_europe.json"
GATEWAY_ID = "1234-1234-6233"
GATEWAY_FIRMWARE_UPDATE_ENTITY_ID = "binary_sensor.tahoma_v2_firmware_update"

SNAPSHOT_FIXTURES = [
    SMOKE_SENSOR,
    HEATING_STATUS,
    CONTACT_SENSOR,
]


@pytest.fixture(autouse=True)
def fixture_platforms() -> Generator[None]:
    """Limit platforms to binary_sensor only."""
    with patch("homeassistant.components.overkiz.PLATFORMS", [Platform.BINARY_SENSOR]):
        yield


@pytest.mark.parametrize(
    "device",
    SNAPSHOT_FIXTURES,
    ids=[Path(device.fixture).name for device in SNAPSHOT_FIXTURES],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_binary_sensor_entities_snapshot(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    device: FixtureDevice,
) -> None:
    """Test representative real setups via snapshot."""
    config_entry = await setup_overkiz_integration(fixture=device.fixture)

    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


async def test_binary_sensor_smoke_state_update(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test event-driven state update for a smoke sensor (notDetected → detected)."""
    await setup_overkiz_integration(fixture=SMOKE_SENSOR.fixture)

    state = hass.states.get(SMOKE_SENSOR.entity_id)
    assert state
    assert state.state == STATE_OFF

    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [
            device_state_changed_event(
                SMOKE_SENSOR.device_url,
                [
                    {
                        "name": OverkizState.CORE_SMOKE.value,
                        "type": 3,
                        "value": "detected",
                    },
                ],
            )
        ],
    )

    state = hass.states.get(SMOKE_SENSOR.entity_id)
    assert state
    assert state.state == STATE_ON


async def test_binary_sensor_tilt_state_update(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test event-driven state update for a tilt sensor (clear → tilted)."""
    await setup_overkiz_integration(fixture=TILT_SENSOR.fixture)

    state = hass.states.get(TILT_SENSOR.entity_id)
    assert state
    assert state.state == STATE_OFF

    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [
            device_state_changed_event(
                TILT_SENSOR.device_url,
                [
                    {
                        "name": OverkizState.CORE_TILTED.value,
                        "type": 6,
                        "value": True,
                    },
                ],
            )
        ],
    )

    state = hass.states.get(TILT_SENSOR.entity_id)
    assert state
    assert state.state == STATE_ON


async def test_binary_sensor_unavailability(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test binary sensor becomes unavailable when device goes offline."""
    await setup_overkiz_integration(fixture=SMOKE_SENSOR.fixture)

    state = hass.states.get(SMOKE_SENSOR.entity_id)
    assert state
    assert state.state != STATE_UNAVAILABLE

    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [device_unavailable_event(SMOKE_SENSOR.device_url)],
    )

    state = hass.states.get(SMOKE_SENSOR.entity_id)
    assert state
    assert state.state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("update_status", "expected_state"),
    [
        pytest.param(UpdateBoxStatus.READY_TO_UPDATE, STATE_ON, id="ready_to_update"),
        pytest.param(
            UpdateBoxStatus.READY_TO_BE_UPDATED_BY_SERVER,
            STATE_ON,
            id="ready_to_be_updated_by_server",
        ),
        pytest.param(UpdateBoxStatus.UPDATING, STATE_ON, id="updating"),
        pytest.param(UpdateBoxStatus.UP_TO_DATE, STATE_OFF, id="up_to_date"),
        pytest.param(UpdateBoxStatus.UNKNOWN, STATE_UNKNOWN, id="unknown"),
    ],
)
async def test_gateway_firmware_update_polling(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    update_status: UpdateBoxStatus,
    expected_state: str,
) -> None:
    """Test the gateway firmware update sensor follows the polled update status."""
    await setup_overkiz_integration(fixture=GATEWAY_FIXTURE)

    assert hass.states.get(GATEWAY_FIRMWARE_UPDATE_ENTITY_ID).state == STATE_OFF
    # The gateways from the setup call are reused, so nothing is polled on startup.
    mock_client.get_gateways.assert_not_awaited()

    await async_poll_gateway_update_status(hass, freezer, mock_client, update_status)

    mock_client.get_gateways.assert_awaited_once_with(refresh=True)
    assert hass.states.get(GATEWAY_FIRMWARE_UPDATE_ENTITY_ID).state == expected_state


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(
            GatewayFirmwareUpdatedEvent(
                name=EventName.GATEWAY_FIRMWARE_UPDATED, gateway_id=GATEWAY_ID
            ),
            id="firmware_updated",
        ),
        pytest.param(
            GatewayFirmwareUpdateCompletedEvent(
                name=EventName.GATEWAY_FIRMWARE_UPDATE_COMPLETED,
                gateway_id=GATEWAY_ID,
            ),
            id="firmware_update_completed",
        ),
    ],
)
async def test_gateway_firmware_update_event_refreshes_gateways(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    event: GatewayFirmwareUpdatedEvent | GatewayFirmwareUpdateCompletedEvent,
) -> None:
    """Test a gateway firmware event refreshes the gateways right away."""
    await setup_overkiz_integration(fixture=GATEWAY_FIXTURE)

    await async_deliver_events(hass, freezer, mock_client, [event])

    mock_client.get_gateways.assert_awaited_once_with(refresh=True)


async def test_gateway_firmware_update_fetch_error_keeps_state(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a failed gateway fetch keeps the last state and retries a day later."""
    await setup_overkiz_integration(fixture=GATEWAY_FIXTURE)

    mock_client.get_gateways.side_effect = MaintenanceError("Maintenance")
    await async_poll_gateway_update_status(
        hass, freezer, mock_client, UpdateBoxStatus.READY_TO_UPDATE
    )

    assert hass.states.get(GATEWAY_FIRMWARE_UPDATE_ENTITY_ID).state == STATE_OFF
    mock_client.get_gateways.assert_awaited_once()

    # The rate limited endpoint is not retried on the next event refresh.
    await async_deliver_events(hass, freezer, mock_client, [])
    mock_client.get_gateways.assert_awaited_once()

    mock_client.get_gateways.side_effect = mock_client._async_get_gateways
    await async_poll_gateway_update_status(
        hass, freezer, mock_client, UpdateBoxStatus.READY_TO_UPDATE
    )

    assert mock_client.get_gateways.await_count == 2
    assert hass.states.get(GATEWAY_FIRMWARE_UPDATE_ENTITY_ID).state == STATE_ON


async def test_gateway_firmware_update_auth_failure_starts_reauth(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test an authentication error while polling gateways starts reauth."""
    config_entry = await setup_overkiz_integration(fixture=GATEWAY_FIXTURE)

    mock_client.get_gateways.side_effect = BadCredentialsError("Bad credentials")
    await async_poll_gateway_update_status(
        hass, freezer, mock_client, UpdateBoxStatus.UP_TO_DATE
    )

    assert config_entry.async_get_active_flows(hass, {SOURCE_REAUTH})


async def test_gateway_firmware_update_not_updatable(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test gateways that can't be updated get no firmware update sensor."""
    await setup_overkiz_integration(fixture="setup/cloud_somfy_myfox_europe.json")

    gateway_entities = {
        entry.unique_id
        for entry in entity_registry.entities.values()
        if entry.unique_id.endswith("-firmware_update")
    }
    # The Somfy Protect and thermostat gateways report NOT_UPDATABLE.
    assert gateway_entities == {"1234-5678-1202-firmware_update"}


@pytest.mark.parametrize(
    "mock_config_entry",
    [
        MockConfigEntry(
            domain=DOMAIN,
            unique_id="1234-5678-6508",
            data={
                "host": "gateway-1234-5678-6508.local:8443",
                "token": "1234123412341234",
                "verify_ssl": True,
                "hub": "somfy_europe",
                "api_type": "local",
            },
        )
    ],
)
async def test_gateway_firmware_update_not_created_for_local_api(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    entity_registry: er.EntityRegistry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the Local API, which has no gateway update status, is not polled."""
    mock_client.server_config = evolve(
        mock_client.server_config, api_type=APIType.LOCAL
    )
    await setup_overkiz_integration(
        fixture="setup/local_somfy_tahoma_switch_europe.json"
    )

    assert not [
        entry
        for entry in entity_registry.entities.values()
        if entry.unique_id.endswith("-firmware_update")
    ]

    await async_poll_gateway_update_status(
        hass, freezer, mock_client, UpdateBoxStatus.READY_TO_UPDATE
    )

    mock_client.get_gateways.assert_not_awaited()
