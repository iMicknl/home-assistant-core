"""Configuration for overkiz tests."""

from collections.abc import Awaitable, Callable, Generator
from dataclasses import dataclass, field
from typing import NamedTuple
from unittest.mock import AsyncMock, Mock, patch

from pyoverkiz.client import OverkizClient
from pyoverkiz.enums import APIType
from pyoverkiz.models import Event, ServerConfig, Setup
import pytest

from homeassistant.components.overkiz.const import CONF_API_TYPE, DOMAIN
from homeassistant.core import HomeAssistant

from . import DEFAULT_SETUP_FIXTURE, load_setup_fixture

from tests.common import MockConfigEntry

type SetupOverkizIntegration = Callable[..., Awaitable[MockConfigEntry]]

TEST_EMAIL = "test@testdomain.com"
TEST_PASSWORD = "test-password"
TEST_SERVER = "somfy_europe"
TEST_GATEWAY_ID = "1234-5678-9123"
TEST_HOST = "gateway-1234-5678-9123.local:8443"
TEST_TOKEN = "1234123412341234"


class FixtureDevice(NamedTuple):
    """Test device binding a fixture file to a device URL and entity id."""

    fixture: str
    device_url: str
    entity_id: str


@dataclass
class MockOverkizClient(OverkizClient):
    """Mock Overkiz client used by integration tests."""

    setup: Setup = field(default_factory=load_setup_fixture)
    event_batches: list[list[Event]] = field(default_factory=list)
    server_config: ServerConfig = field(
        default_factory=lambda: ServerConfig(
            name="Somfy",
            endpoint="https://example.test/enduser-mobile-web/enduserAPI",
            manufacturer="Somfy",
            configuration_url=None,
            server=None,
            api_type=APIType.CLOUD,
        )
    )

    def __post_init__(self) -> None:
        """Initialize async client methods."""
        self._execution_id = 0
        self.login = AsyncMock(return_value=True)
        self.get_setup = AsyncMock(side_effect=self._async_get_setup)
        self.get_devices = AsyncMock(side_effect=self._async_get_devices)
        self.get_gateways = AsyncMock(return_value=[Mock(id=TEST_GATEWAY_ID)])
        self.discover_gateways = AsyncMock(return_value=[])
        self.get_action_groups = AsyncMock(return_value=[])
        self.fetch_events = AsyncMock(side_effect=self._async_fetch_events)
        self.get_current_executions = AsyncMock(return_value=[])
        self.cancel_execution = AsyncMock(return_value=None)
        self.execute_action_group = AsyncMock(
            side_effect=self._async_execute_action_group
        )

    def set_setup_fixture(self, fixture: str) -> None:
        """Load a setup fixture for the next integration setup."""
        self.setup = load_setup_fixture(fixture)
        self.event_batches.clear()
        self.reset_mock()

    def queue_events(self, *batches: list[Event]) -> None:
        """Queue batches of events returned by fetch_events."""
        self.event_batches.extend(batches)

    def reset_mock(self) -> None:
        """Reset call history while keeping configured behavior."""
        self.login.reset_mock()
        self.get_setup.reset_mock()
        self.get_devices.reset_mock()
        self.get_gateways.reset_mock()
        self.discover_gateways.reset_mock()
        self.get_action_groups.reset_mock()
        self.fetch_events.reset_mock()
        self.get_current_executions.reset_mock()
        self.cancel_execution.reset_mock()
        self.execute_action_group.reset_mock()

    async def _async_get_setup(self) -> Setup:
        """Return the configured setup."""
        return self.setup

    async def _async_get_devices(self, refresh: bool = False) -> list:
        """Return the configured devices."""
        return self.setup.devices

    async def _async_fetch_events(self) -> list[Event]:
        """Return queued event batches one refresh at a time."""
        if self.event_batches:
            return self.event_batches.pop(0)
        return []

    async def _async_execute_action_group(self, *args, **kwargs) -> str:
        """Return a unique execution id for each action group."""
        self._execution_id += 1
        return f"exec-{self._execution_id}"


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a Cloud API config entry (the default used by platform tests)."""
    return MockConfigEntry(
        title="Somfy TaHoma Switch",
        domain=DOMAIN,
        unique_id=TEST_GATEWAY_ID,
        data={"username": TEST_EMAIL, "password": TEST_PASSWORD, "hub": TEST_SERVER},
    )


@pytest.fixture
def mock_local_config_entry() -> MockConfigEntry:
    """Return a Local API config entry backed by a token."""
    return MockConfigEntry(
        title=TEST_HOST,
        domain=DOMAIN,
        unique_id=TEST_GATEWAY_ID,
        minor_version=2,
        data={
            "host": TEST_HOST,
            "token": TEST_TOKEN,
            "verify_ssl": True,
            "hub": TEST_SERVER,
            "api_type": "local",
        },
    )


@pytest.fixture
def mock_rexel_config_entry() -> MockConfigEntry:
    """Return a Rexel config entry backed by an OAuth2 token bundle."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_GATEWAY_ID,
        data={
            "auth_implementation": DOMAIN,
            "token": {"access_token": "mock-access-token"},
            "hub": "rexel",
            "gateway_id": TEST_GATEWAY_ID,
        },
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Mock setting up a config entry."""
    with patch(
        "homeassistant.components.overkiz.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_client() -> Generator[MockOverkizClient]:
    """Return a mock Overkiz client, patched in at the library boundary.

    Patching ``OverkizClient`` where the integration constructs it (both the
    setup path and the config flow) means the same mock backs the config flow
    tests and the platform tests without touching the integration's own
    ``create_*_client`` helpers.
    """
    client = MockOverkizClient()

    with (
        patch("homeassistant.components.overkiz.OverkizClient", return_value=client),
        patch(
            "homeassistant.components.overkiz.config_flow.OverkizClient",
            return_value=client,
        ),
    ):
        yield client


@pytest.fixture
def setup_overkiz_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_client: MockOverkizClient,
) -> SetupOverkizIntegration:
    """Return a helper to set up the Overkiz integration from a chosen fixture."""

    async def _setup(
        *,
        fixture: str = DEFAULT_SETUP_FIXTURE,
        config_entry: MockConfigEntry | None = None,
    ) -> MockConfigEntry:
        entry = config_entry or mock_config_entry
        entry.add_to_hass(hass)

        mock_client.set_setup_fixture(fixture)
        # Match the fake client's transport to the entry being set up, so the
        # cloud-only default doesn't mask local-specific entity behavior.
        mock_client.server_config.api_type = APIType(
            entry.data.get(CONF_API_TYPE, APIType.CLOUD)
        )

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        return entry

    return _setup


@pytest.fixture
async def init_integration(
    setup_overkiz_integration: SetupOverkizIntegration,
) -> MockConfigEntry:
    """Set up the Overkiz integration for testing."""
    return await setup_overkiz_integration()
