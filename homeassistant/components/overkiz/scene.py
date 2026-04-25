"""Support for Overkiz scenes."""

from __future__ import annotations

from typing import Any

from pyoverkiz.client import OverkizClient
from pyoverkiz.models import PersistedActionGroup

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OverkizDataConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OverkizDataConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Overkiz scenes from a config entry."""
    data = entry.runtime_data

    async_add_entities(
        OverkizScene(action_group, data.coordinator.client)
        for action_group in data.action_groups
    )


class OverkizScene(Scene):
    """Representation of an Overkiz Scene."""

    def __init__(
        self, action_group: PersistedActionGroup, client: OverkizClient
    ) -> None:
        """Initialize the scene."""
        self.action_group = action_group
        self.client = client
        self._attr_name = self.action_group.label
        self._attr_unique_id = self.action_group.oid

    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene."""
        await self.client.execute_persisted_action_group(self.action_group.oid)
