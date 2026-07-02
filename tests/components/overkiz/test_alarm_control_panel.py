"""Tests for the Overkiz alarm_control_panel platform."""

from collections.abc import Generator
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from pyoverkiz.enums import OverkizState
import pytest

from homeassistant.components.alarm_control_panel import AlarmControlPanelState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .conftest import MockOverkizClient, SetupOverkizIntegration
from .helpers import async_deliver_events, device_state_changed_event

MYFOX_ALARM = "alarm_control_panel.home_alarm"
MYFOX_ALARM_FIXTURE = "setup/cloud_somfy_myfox_europe.json"
MYFOX_ALARM_DEVICE_URL = "myfox://SOMFY_PROTECT-1234567890ABCDEF/site_alarm"


@pytest.fixture(autouse=True)
def fixture_platforms() -> Generator[None]:
    """Limit platforms to alarm_control_panel only."""
    with patch(
        "homeassistant.components.overkiz.PLATFORMS",
        [Platform.ALARM_CONTROL_PANEL],
    ):
        yield


async def test_myfox_disarm_clears_stale_intrusion(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_client: MockOverkizClient,
    setup_overkiz_integration: SetupOverkizIntegration,
) -> None:
    """Test the panel clears triggered when a disarm-only event is received.

    Somfy's event stream never resets core:IntrusionState once it reports
    "detected"; only myfox:AlarmStatusState=disarmed is broadcast on disarm.
    Before the fix, that stale intrusion flag kept the panel stuck on
    triggered until the integration was reloaded.
    """
    await setup_overkiz_integration(fixture=MYFOX_ALARM_FIXTURE)

    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [
            device_state_changed_event(
                device_url=MYFOX_ALARM_DEVICE_URL,
                device_states=[
                    {
                        "name": OverkizState.MYFOX_ALARM_STATUS,
                        "type": 3,
                        "value": "armed",
                    },
                    {
                        "name": OverkizState.CORE_INTRUSION,
                        "type": 3,
                        "value": "detected",
                    },
                ],
            )
        ],
    )

    state = hass.states.get(MYFOX_ALARM)
    assert state is not None
    assert state.state == AlarmControlPanelState.TRIGGERED

    await async_deliver_events(
        hass,
        freezer,
        mock_client,
        [
            device_state_changed_event(
                device_url=MYFOX_ALARM_DEVICE_URL,
                device_states=[
                    {
                        "name": OverkizState.MYFOX_ALARM_STATUS,
                        "type": 3,
                        "value": "disarmed",
                    }
                ],
            )
        ],
    )

    state = hass.states.get(MYFOX_ALARM)
    assert state is not None
    assert state.state == AlarmControlPanelState.DISARMED
