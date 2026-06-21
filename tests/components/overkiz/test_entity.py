"""Tests for the Overkiz entity base classes."""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .conftest import SetupOverkizIntegration


@pytest.fixture(autouse=True)
def fixture_platforms() -> Generator[None]:
    """Limit platforms to sensor only."""
    with patch("homeassistant.components.overkiz.PLATFORMS", [Platform.SENSOR]):
        yield


@pytest.mark.parametrize(
    ("fixture", "entity_id", "friendly_name"),
    [
        # Sub-device sharing its label with the base device: the label must not
        # be repeated (regression test for the doubled friendly name).
        pytest.param(
            "setup/cloud_somfy_myfox_europe.json",
            "sensor.electric_energy_consumption_3",
            "** ** ** Electric energy consumption",
            id="sub_device_same_label_as_base",
        ),
        # Sub-device with a distinct label keeps its label as a prefix.
        pytest.param(
            "setup/cloud_nexity_rail_din_europe.json",
            "sensor.maple_residence_garden_radiator_bathroom_temperature_sensor_temperature",
            "Garden Radiator Bathroom Temperature Sensor Temperature",
            id="sub_device_distinct_label",
        ),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_sub_device_entity_name(
    hass: HomeAssistant,
    setup_overkiz_integration: SetupOverkizIntegration,
    fixture: str,
    entity_id: str,
    friendly_name: str,
) -> None:
    """Test friendly names for sub-device entities."""
    await setup_overkiz_integration(fixture=fixture)

    state = hass.states.get(entity_id)
    assert state
    assert state.attributes["friendly_name"] == friendly_name
