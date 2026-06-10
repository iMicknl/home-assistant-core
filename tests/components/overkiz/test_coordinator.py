"""Tests for the Overkiz data update coordinator."""

from unittest.mock import Mock, patch

from aiohttp import ClientConnectorError
from freezegun.api import FrozenDateTimeFactory
from pyoverkiz.enums import ExecutionState
from pyoverkiz.exceptions import (
    InvalidEventListenerIdError,
    MaintenanceError,
    ServiceUnavailableError,
    TooManyConcurrentRequestsError,
    TooManyRequestsError,
)
import pytest

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN, SERVICE_CLOSE_COVER
from homeassistant.components.overkiz.const import DOMAIN, UPDATE_INTERVAL
from homeassistant.components.overkiz.coordinator import OverkizDataUpdateCoordinator
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import FixtureDevice, MockOverkizClient, SetupOverkizIntegration
from .helpers import async_deliver_events, execution_state_changed_event

from tests.common import async_fire_time_changed

TEMPERATURE_SENSOR = FixtureDevice(
    "setup/cloud_nexity_rail_din_europe.json",
    "io://1234-5678-1698/15702199#2",
    "sensor.maple_residence_garden_radiator_bathroom_temperature_sensor_temperature",
)

# A bidirectional (IO) cover that reports command results via execution events.
IO_SHUTTER = FixtureDevice(
    "setup/cloud_somfy_tahoma_v2_europe.json",
    "io://1234-1234-6233/12184029",
    "cover.office_garden_house_shutter",
)
# A one-way (RTS) cover that never reports execution results.
RTS_SHUTTER = FixtureDevice(
    "setup/local_somfy_tahoma_v2_europe.json",
    "rts://1234-5678-3293/16757826",
    "cover.kitchen_pergola",
)


async def _close_cover(hass: HomeAssistant, entity_id: str) -> None:
    """Call the close cover service, blocking until it returns."""
    await hass.services.async_call(
        COVER_DOMAIN,
        SERVICE_CLOSE_COVER,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )


async def test_command_failure_raises(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
) -> None:
    """A command rejected by the device raises HomeAssistantError to the caller."""
    await setup_overkiz_integration(fixture=IO_SHUTTER.fixture)

    mock_client.execution_result_state = ExecutionState.FAILED
    mock_client.execution_result_failure_type = "PRIORITY_LOCK__USER"

    with pytest.raises(HomeAssistantError, match="PRIORITY_LOCK__USER"):
        await _close_cover(hass, IO_SHUTTER.entity_id)


async def test_command_accepted_returns(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
) -> None:
    """A command accepted with IN_PROGRESS returns without raising."""
    await setup_overkiz_integration(fixture=IO_SHUTTER.fixture)

    await _close_cover(hass, IO_SHUTTER.entity_id)

    assert mock_client.execute_action_group.await_count == 1
    # The execution stays tracked until it terminates, so cover entities can
    # still derive their moving state from it.
    coordinator = mock_config_entry_coordinator(hass)
    assert coordinator.executions
    assert not coordinator.execution_results


async def test_command_result_timeout_is_optimistic(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
) -> None:
    """A command with no reported result returns optimistically, no raise."""
    await setup_overkiz_integration(fixture=IO_SHUTTER.fixture)

    mock_client.execution_result_state = None  # gateway never reports back

    with patch(
        "homeassistant.components.overkiz.executor.EXECUTION_RESULT_TIMEOUT", 0.01
    ):
        await _close_cover(hass, IO_SHUTTER.entity_id)

    assert mock_client.execute_action_group.await_count == 1
    coordinator = mock_config_entry_coordinator(hass)
    assert not coordinator.execution_results


async def test_command_on_stateless_device_is_fire_and_forget(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
) -> None:
    """An RTS (one-way) command returns immediately without awaiting a result."""
    await setup_overkiz_integration(fixture=RTS_SHUTTER.fixture)

    mock_client.execution_result_state = None  # RTS never reports back

    await _close_cover(hass, RTS_SHUTTER.entity_id)

    assert mock_client.execute_action_group.await_count == 1
    coordinator = mock_config_entry_coordinator(hass)
    assert not coordinator.execution_results


async def test_mid_movement_failure_is_logged_not_raised(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failure after IN_PROGRESS (e.g. blocked by hazard) is logged, not raised.

    The command has already returned at IN_PROGRESS, so the late terminal FAILED
    cannot be raised to the caller; it must only be logged and must clean up.
    """
    await setup_overkiz_integration(fixture=IO_SHUTTER.fixture)

    # The command is accepted (IN_PROGRESS) and returns without raising.
    await _close_cover(hass, IO_SHUTTER.entity_id)

    # Later, the cover hits an obstacle and the execution terminates as FAILED.
    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [
            execution_state_changed_event(
                exec_id="exec-1",
                new_state=ExecutionState.FAILED,
                old_state=ExecutionState.IN_PROGRESS,
                failure_type="WHILEEXEC_BLOCKED_BY_HAZARD",
            )
        ],
    )

    assert "WHILEEXEC_BLOCKED_BY_HAZARD" in caplog.text
    coordinator = mock_config_entry_coordinator(hass)
    assert not coordinator.executions
    assert not coordinator.execution_results


def mock_config_entry_coordinator(
    hass: HomeAssistant,
) -> OverkizDataUpdateCoordinator:
    """Return the coordinator of the single loaded Overkiz config entry."""
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    return entry.runtime_data.coordinator


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
