"""Tests for the Overkiz number platform."""

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from pyoverkiz.enums import OverkizState
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import FixtureDevice, MockOverkizClient, SetupOverkizIntegration
from .helpers import (
    assert_command_call,
    assert_commands_call,
    async_deliver_events,
    device_state_changed_event,
    device_unavailable_event,
)

from tests.common import snapshot_platform

MEMORIZED_POSITION = FixtureDevice(
    "setup/cloud_somfy_tahoma_v2_europe.json",
    "io://1234-1234-6233/12184029",
    "number.office_garden_house_shutter_my_position",
)
OFFICE_BLINDS_MEMORIZED_POSITION = FixtureDevice(
    "setup/local_somfy_tahoma_switch_europe.json",
    "io://1234-5678-6508/4877511",
    "number.office_blinds_my_position",
)
EXPECTED_NUMBER_OF_SHOWER = FixtureDevice(
    "setup/cloud_atlantic_cozytouch.json",
    "io://1234-5678-5643/109286#1",
    "number.my_home_patio_water_heating_expected_number_of_shower",
)
COMFORT_ROOM_TEMPERATURE = FixtureDevice(
    "setup/cloud_nexity_rail_din_europe.json",
    "ovp://1234-5678-1698/374762#1",
    "number.maple_residence_terrace_radiator_comfort_room_temperature",
)
MBL_BOOST_DURATION = FixtureDevice(
    "setup/cloud_atlantic_cozytouch.json",
    "modbuslink://1234-5678-5643/2#1",
    "number.my_home_bathroom_water_heater_boost_mode_duration",
)
# The MBL fixture's boost window runs 2026-06-21 13:12:01 to 2026-06-22 13:12:01,
# read as naive time in the HA time zone (US/Pacific in tests).
MBL_BOOST_WINDOW_ACTIVE = "2026-06-22 00:00:00+00:00"
MBL_BOOST_WINDOW_EXPIRED = "2026-06-23 00:00:00+00:00"
TOWEL_DRYER_BOOST_MODE_DURATION = FixtureDevice(
    "setup/cloud_atlantic_cozytouch.json",
    "io://1234-5678-5643/5237136#1",
    "number.my_home_bathroom_towel_dryer_boost_mode_duration",
)
TOWEL_DRYER_DRYING_DURATION = FixtureDevice(
    "setup/cloud_atlantic_cozytouch.json",
    "io://1234-5678-5643/5237136#1",
    "number.my_home_bathroom_towel_dryer_drying_duration",
)

SNAPSHOT_FIXTURES = [
    MEMORIZED_POSITION,
    OFFICE_BLINDS_MEMORIZED_POSITION,
    EXPECTED_NUMBER_OF_SHOWER,
    COMFORT_ROOM_TEMPERATURE,
]


@pytest.fixture(autouse=True)
def fixture_platforms() -> Generator[None]:
    """Limit platforms to number only."""
    with patch("homeassistant.components.overkiz.PLATFORMS", [Platform.NUMBER]):
        yield


@pytest.mark.parametrize(
    "device",
    SNAPSHOT_FIXTURES,
    ids=[Path(device.fixture).name for device in SNAPSHOT_FIXTURES],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_number_entities_snapshot(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    freezer: FrozenDateTimeFactory,
    device: FixtureDevice,
) -> None:
    """Test representative real setups via snapshot."""
    # The MBL boost duration depends on the current time.
    freezer.move_to(MBL_BOOST_WINDOW_ACTIVE)
    config_entry = await setup_overkiz_integration(fixture=device.fixture)

    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


@pytest.mark.parametrize(
    ("device", "value", "command_name"),
    [
        pytest.param(
            EXPECTED_NUMBER_OF_SHOWER, 3, "setExpectedNumberOfShower", id="shower"
        ),
        pytest.param(
            TOWEL_DRYER_BOOST_MODE_DURATION,
            45,
            "setTowelDryerBoostModeDuration",
            id="towel_dryer_boost_mode_duration",
        ),
        pytest.param(
            TOWEL_DRYER_DRYING_DURATION,
            90,
            "setDryingDuration",
            id="towel_dryer_drying_duration",
        ),
    ],
)
async def test_number_set_value(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    device: FixtureDevice,
    value: int,
    command_name: str,
) -> None:
    """Test setting a number value sends the correct command."""
    await setup_overkiz_integration(fixture=device.fixture)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: device.entity_id, ATTR_VALUE: value},
        blocking=True,
    )

    assert_command_call(
        mock_client,
        device_url=device.device_url,
        command_name=command_name,
        parameters=[value],
    )


async def test_number_inverted_memorized_position_set(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
) -> None:
    """Test that setting a cover's "My position" inverts before sending."""
    await setup_overkiz_integration(fixture=OFFICE_BLINDS_MEMORIZED_POSITION.fixture)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: OFFICE_BLINDS_MEMORIZED_POSITION.entity_id, ATTR_VALUE: 15},
        blocking=True,
    )

    assert_command_call(
        mock_client,
        device_url=OFFICE_BLINDS_MEMORIZED_POSITION.device_url,
        command_name="setMemorized1Position",
        parameters=[85],
    )


async def test_number_dynamic_min_max(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
) -> None:
    """Test that min/max values are read from device states when available."""
    await setup_overkiz_integration(fixture=EXPECTED_NUMBER_OF_SHOWER.fixture)

    state = hass.states.get(EXPECTED_NUMBER_OF_SHOWER.entity_id)
    assert state
    assert state.attributes["min"] == 2
    assert state.attributes["max"] == 4


async def test_number_state_update(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test event-driven state update for a number entity."""
    await setup_overkiz_integration(fixture=EXPECTED_NUMBER_OF_SHOWER.fixture)

    state = hass.states.get(EXPECTED_NUMBER_OF_SHOWER.entity_id)
    assert state
    assert state.state == "4"

    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [
            device_state_changed_event(
                device_url=EXPECTED_NUMBER_OF_SHOWER.device_url,
                device_states=[
                    {
                        "name": OverkizState.CORE_EXPECTED_NUMBER_OF_SHOWER.value,
                        "type": 1,
                        "value": 3,
                    },
                ],
            )
        ],
    )

    state = hass.states.get(EXPECTED_NUMBER_OF_SHOWER.entity_id)
    assert state.state == "3"


async def test_number_unavailability(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test number becomes unavailable when device goes offline."""
    await setup_overkiz_integration(fixture=EXPECTED_NUMBER_OF_SHOWER.fixture)

    state = hass.states.get(EXPECTED_NUMBER_OF_SHOWER.entity_id)
    assert state
    assert state.state != STATE_UNAVAILABLE

    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [
            device_unavailable_event(
                device_url=EXPECTED_NUMBER_OF_SHOWER.device_url,
            )
        ],
    )

    assert (
        hass.states.get(EXPECTED_NUMBER_OF_SHOWER.entity_id).state == STATE_UNAVAILABLE
    )


async def test_mbl_boost_duration_set_opens_window(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
) -> None:
    """Test setting boost duration sets a start/end window then enables boost."""
    freezer.move_to("2026-05-28 12:00:00+00:00")
    await setup_overkiz_integration(fixture=MBL_BOOST_DURATION.fixture)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: MBL_BOOST_DURATION.entity_id, ATTR_VALUE: 3},
        blocking=True,
    )

    now_date = {
        "year": 2026,
        "month": 5,
        "day": 28,
        "hour": 5,
        "minute": 0,
        "second": 0,
        "weekday": 3,
    }
    end_date = {**now_date, "day": 31, "weekday": 6}
    assert_commands_call(
        mock_client,
        device_url=MBL_BOOST_DURATION.device_url,
        commands=[
            ("setBoostStartDate", [now_date]),
            ("setBoostEndDate", [end_date]),
            ("setBoostMode", ["on"]),
        ],
    )


async def test_mbl_boost_duration_zero_cancels(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
) -> None:
    """Test setting boost duration to 0 turns boost off."""
    await setup_overkiz_integration(fixture=MBL_BOOST_DURATION.fixture)

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: MBL_BOOST_DURATION.entity_id, ATTR_VALUE: 0},
        blocking=True,
    )

    assert_command_call(
        mock_client,
        device_url=MBL_BOOST_DURATION.device_url,
        command_name="setBoostMode",
        parameters=["off"],
    )


def _mbl_boost_mode(value: str) -> dict[str, Any]:
    return {
        "name": OverkizState.MODBUSLINK_DHW_BOOST_MODE.value,
        "type": 3,
        "value": value,
    }


MBL_BOOST_END_DATE_CLEARED = {
    "name": OverkizState.CORE_BOOST_END_DATE.value,
    "type": 0,
    "value": None,
}


@pytest.mark.parametrize(
    ("now", "device_states", "expected_state"),
    [
        pytest.param(
            MBL_BOOST_WINDOW_ACTIVE,
            [_mbl_boost_mode("on")],
            "1",
            id="timed_boost_inside_window",
        ),
        pytest.param(
            MBL_BOOST_WINDOW_ACTIVE,
            [_mbl_boost_mode("prog")],
            "1",
            id="prog_boost_inside_window",
        ),
        pytest.param(
            MBL_BOOST_WINDOW_EXPIRED,
            [_mbl_boost_mode("on")],
            STATE_UNKNOWN,
            id="untimed_boost_with_expired_window",
        ),
        pytest.param(
            MBL_BOOST_WINDOW_ACTIVE,
            [_mbl_boost_mode("on"), MBL_BOOST_END_DATE_CLEARED],
            STATE_UNKNOWN,
            id="boost_without_window",
        ),
        pytest.param(
            MBL_BOOST_WINDOW_ACTIVE,
            [_mbl_boost_mode("off")],
            "0",
            id="boost_off_inside_window",
        ),
        pytest.param(
            MBL_BOOST_WINDOW_EXPIRED,
            [_mbl_boost_mode("off")],
            "0",
            id="boost_off_expired_window",
        ),
    ],
)
async def test_mbl_boost_duration_state(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
    now: str,
    device_states: list[dict[str, Any]],
    expected_state: str,
) -> None:
    """Test the duration only reports the window length while it is current."""
    freezer.move_to(now)
    await setup_overkiz_integration(fixture=MBL_BOOST_DURATION.fixture)

    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [
            device_state_changed_event(
                device_url=MBL_BOOST_DURATION.device_url,
                device_states=device_states,
            )
        ],
    )

    state = hass.states.get(MBL_BOOST_DURATION.entity_id)
    assert state
    assert state.state == expected_state
