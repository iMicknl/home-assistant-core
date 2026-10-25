"""Tests for the Overkiz button platform."""

from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from pyoverkiz.enums import UpdateBoxStatus
import pytest
from pytest_homeassistant.common import snapshot_platform
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import FixtureDevice, MockOverkizClient, SetupOverkizIntegration
from .helpers import (
    assert_command_call,
    async_deliver_events,
    async_poll_gateways,
    device_unavailable_event,
)

MY_POSITION = FixtureDevice(
    "setup/cloud_somfy_tahoma_v2_europe.json",
    "io://1234-1234-6233/12184029",
    "button.office_garden_house_shutter_my_position",
)
IDENTIFY = FixtureDevice(
    "setup/cloud_somfy_tahoma_v2_europe.json",
    "io://1234-1234-6233/12184029",
    "button.office_garden_house_shutter_identify",
)
GO_TO_ALIAS = FixtureDevice(
    "setup/local_somfy_tahoma_switch_europe_2.json",
    "io://1234-5678-1516/77700",
    "button.roof_window_my_position",
)
CHECK_EVENT_TRIGGER = FixtureDevice(
    "setup/cloud_nexity_rail_din_europe.json",
    "io://1234-5678-1698/8907539",
    "button.maple_residence_living_room_smoke_detector_test",
)
STEP_POSITIVE = FixtureDevice(
    "setup/cloud_somfy_connexoon_rts_asia.json",
    "rts://1234-1234-6362/16752757",
    "button.palm_court_led_strip_brightness_up",
)
STEP_NEGATIVE = FixtureDevice(
    "setup/cloud_somfy_connexoon_rts_asia.json",
    "rts://1234-1234-6362/16752757",
    "button.palm_court_led_strip_brightness_down",
)
GATEWAY_FIRMWARE_UPDATE = FixtureDevice(
    "setup/cloud_somfy_tahoma_switch_europe.json",
    "internal://1234-5678-6867/pod/0",
    "button.tahoma_switch_install_firmware_update",
)

SNAPSHOT_FIXTURES = [
    MY_POSITION,
    GO_TO_ALIAS,
    CHECK_EVENT_TRIGGER,
    STEP_POSITIVE,
]


@pytest.fixture(autouse=True)
def fixture_platforms() -> Generator[None]:
    """Limit platforms to button only."""
    with patch("homeassistant.components.overkiz.PLATFORMS", [Platform.BUTTON]):
        yield


@pytest.mark.parametrize(
    "device",
    SNAPSHOT_FIXTURES,
    ids=[Path(device.fixture).name for device in SNAPSHOT_FIXTURES],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_button_entities_snapshot(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    device: FixtureDevice,
) -> None:
    """Test representative real setups via snapshot."""
    config_entry = await setup_overkiz_integration(fixture=device.fixture)

    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)


async def test_button_press(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
) -> None:
    """Test pressing a button without arguments sends the correct command."""
    await setup_overkiz_integration(fixture=MY_POSITION.fixture)

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: MY_POSITION.entity_id},
        blocking=True,
    )

    assert_command_call(
        mock_client,
        device_url=MY_POSITION.device_url,
        command_name="my",
    )


@pytest.mark.parametrize(
    ("device", "command_name", "parameters"),
    [
        pytest.param(GO_TO_ALIAS, "goToAlias", ["1"], id="go_to_alias"),
        pytest.param(STEP_POSITIVE, "stepPositive", [5], id="step_positive"),
        pytest.param(STEP_NEGATIVE, "stepNegative", [5], id="step_negative"),
    ],
)
async def test_button_press_with_args(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    device: FixtureDevice,
    command_name: str,
    parameters: list[Any],
) -> None:
    """Test pressing a button with arguments sends the correct command."""
    await setup_overkiz_integration(fixture=device.fixture)

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: device.entity_id},
        blocking=True,
    )

    assert_command_call(
        mock_client,
        device_url=device.device_url,
        command_name=command_name,
        parameters=parameters,
    )


async def test_button_unavailability(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test button becomes unavailable when device goes offline."""
    await setup_overkiz_integration(fixture=MY_POSITION.fixture)

    state = hass.states.get(MY_POSITION.entity_id)
    assert state
    assert state.state != STATE_UNAVAILABLE

    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [
            device_unavailable_event(
                device_url=MY_POSITION.device_url,
            )
        ],
    )

    assert hass.states.get(MY_POSITION.entity_id).state == STATE_UNAVAILABLE


async def test_gateway_firmware_update_press(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test pressing the firmware update button sends update to the gateway pod."""
    await setup_overkiz_integration(fixture=GATEWAY_FIRMWARE_UPDATE.fixture)
    await async_poll_gateways(
        hass, freezer, mock_client, update_status=UpdateBoxStatus.READY_TO_UPDATE
    )

    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: GATEWAY_FIRMWARE_UPDATE.entity_id},
        blocking=True,
    )

    assert_command_call(
        mock_client,
        device_url=GATEWAY_FIRMWARE_UPDATE.device_url,
        command_name="update",
    )


async def test_gateway_firmware_update_press_without_update(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    mock_client: MockOverkizClient,
) -> None:
    """Test pressing the firmware update button without a pending update fails."""
    await setup_overkiz_integration(fixture=GATEWAY_FIRMWARE_UPDATE.fixture)

    with pytest.raises(ServiceValidationError) as exc_info:
        await hass.services.async_call(
            BUTTON_DOMAIN,
            SERVICE_PRESS,
            {ATTR_ENTITY_ID: GATEWAY_FIRMWARE_UPDATE.entity_id},
            blocking=True,
        )

    assert exc_info.value.translation_key == "no_firmware_update_available"
    mock_client.execute_action_group.assert_not_awaited()
