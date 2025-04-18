"""Tests for Overkiz config flow."""

from __future__ import annotations

from collections.abc import Generator
from ipaddress import ip_address
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientConnectorCertificateError, ClientError
from pyoverkiz.exceptions import (
    BadCredentialsException,
    MaintenanceException,
    NotSuchTokenException,
    TooManyAttemptsBannedException,
    TooManyRequestsException,
    UnknownUserException,
)
import pytest

from homeassistant import config_entries
from homeassistant.components.overkiz.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from tests.common import MockConfigEntry

TEST_EMAIL = "test@testdomain.com"
TEST_EMAIL2 = "test@testdomain.nl"
TEST_PASSWORD = "test-password"
TEST_PASSWORD2 = "test-password2"
TEST_SERVER = "somfy_europe"
TEST_SERVER2 = "hi_kumo_europe"
TEST_SERVER_COZYTOUCH = "atlantic_cozytouch"
TEST_GATEWAY_ID = "1234-5678-9123"
TEST_GATEWAY_ID2 = "4321-5678-9123"
TEST_GATEWAY_ID3 = "SOMFY_PROTECT-v0NT53occUBPyuJRzx59kalW1hFfzimN"

TEST_HOST = "gateway-1234-5678-9123.local:8443"
TEST_HOST2 = "192.168.11.104:8443"
TEST_TOKEN = "1234123412341234"

# Common test error mappings
ERROR_MAPPING = [
    (BadCredentialsException, "invalid_auth"),
    (TooManyRequestsException, "too_many_requests"),
    (TimeoutError, "cannot_connect"),
    (ClientError, "cannot_connect"),
    (MaintenanceException, "server_in_maintenance"),
    (TooManyAttemptsBannedException, "too_many_attempts"),
    (UnknownUserException, "unsupported_hardware"),
    (Exception, "unknown"),
]

# Additional mapping for local API
LOCAL_ERROR_MAPPING = [
    *ERROR_MAPPING,
    (
        ClientConnectorCertificateError(Mock(host=TEST_HOST), Exception),
        "certificate_verify_failed",
    ),
    (NotSuchTokenException, "invalid_auth"),
]

# Mock gateway responses
MOCK_GATEWAY_RESPONSE = [Mock(id=TEST_GATEWAY_ID)]
MOCK_GATEWAY2_RESPONSE = [Mock(id=TEST_GATEWAY_ID3), Mock(id=TEST_GATEWAY_ID2)]

# Zeroconf discovery info
FAKE_ZERO_CONF_INFO = ZeroconfServiceInfo(
    ip_address=ip_address("192.168.0.51"),
    ip_addresses=[ip_address("192.168.0.51")],
    port=443,
    hostname=f"gateway-{TEST_GATEWAY_ID}.local.",
    type="_kizbox._tcp.local.",
    name=f"gateway-{TEST_GATEWAY_ID}._kizbox._tcp.local.",
    properties={
        "api_version": "1",
        "gateway_pin": TEST_GATEWAY_ID,
        "fw_version": "2021.5.4-29",
    },
)

FAKE_ZERO_CONF_INFO_LOCAL = ZeroconfServiceInfo(
    ip_address=ip_address("192.168.0.51"),
    ip_addresses=[ip_address("192.168.0.51")],
    port=8443,
    hostname=f"gateway-{TEST_GATEWAY_ID}.local.",
    type="_kizboxdev._tcp.local.",
    name=f"gateway-{TEST_GATEWAY_ID}._kizboxdev._tcp.local.",
    properties={
        "api_version": "1",
        "gateway_pin": TEST_GATEWAY_ID,
        "fw_version": "2021.5.4-29",
    },
)


@pytest.fixture(name="mock_setup")
def mock_setup_fixture() -> Generator[tuple[AsyncMock, AsyncMock]]:
    """Mock setup."""
    with (
        patch("pyoverkiz.client.OverkizClient.login", return_value=True) as mock_login,
        patch(
            "pyoverkiz.client.OverkizClient.get_gateways",
            return_value=MOCK_GATEWAY_RESPONSE,
        ) as mock_gateways,
    ):
        yield mock_login, mock_gateways


async def init_config_flow_cloud(
    hass: HomeAssistant,
    mock_setup: tuple[AsyncMock, AsyncMock],
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Test the cloud API configuration flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"hub": TEST_SERVER},
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["step_id"] == "local_or_cloud"

    result3 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"api_type": "cloud"},
    )
    assert result3["type"] == FlowResultType.FORM
    assert result3["step_id"] == "cloud"

    return result


async def init_config_flow_local(
    hass: HomeAssistant,
    mock_setup: tuple[AsyncMock, AsyncMock],
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Test the local API configuration flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"hub": TEST_SERVER},
    )
    assert result2["type"] == FlowResultType.FORM
    assert result2["step_id"] == "local_or_cloud"

    result3 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"api_type": "local"},
    )
    assert result3["type"] == FlowResultType.FORM
    assert result3["step_id"] == "local"

    return result


async def complete_cloud_flow(
    hass: HomeAssistant,
    result: dict[str, Any],
    mock_setup: tuple[AsyncMock, AsyncMock],
) -> dict[str, Any]:
    """Complete the cloud configuration flow."""
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"username": TEST_EMAIL, "password": TEST_PASSWORD},
    )


async def complete_local_flow(
    hass: HomeAssistant,
    result: dict[str, Any],
    mock_setup: tuple[AsyncMock, AsyncMock],
) -> dict[str, Any]:
    """Complete the local configuration flow."""
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": TEST_HOST,
            "token": TEST_TOKEN,
            "verify_ssl": True,
        },
    )


def create_mock_entry(
    *,
    unique_id: str = TEST_GATEWAY_ID,
    version: int = 2,
    data: dict[str, Any],
) -> MockConfigEntry:
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=unique_id,
        version=version,
        data=data,
    )


@pytest.mark.parametrize(("exception", "error"), ERROR_MAPPING)
async def test_cloud_errors(
    hass: HomeAssistant,
    mock_setup: tuple[AsyncMock, AsyncMock],
    exception: type[Exception],
    error: str,
) -> None:
    """Test we handle cloud API errors."""
    mock_login, _ = mock_setup
    mock_login.side_effect = exception

    result = await init_config_flow_cloud(hass, mock_setup)
    result2 = await complete_cloud_flow(hass, result, mock_setup)

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": error}

    # Test recovery from error
    mock_login.side_effect = None
    result3 = await complete_cloud_flow(hass, result, mock_setup)

    assert result3["type"] == FlowResultType.CREATE_ENTRY
    assert result3["title"] == TEST_EMAIL
    assert result3["data"] == {
        "username": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "hub": TEST_SERVER,
        "api_type": "cloud",
    }
    assert result3["result"].unique_id == TEST_GATEWAY_ID


@pytest.mark.parametrize(("exception", "error"), LOCAL_ERROR_MAPPING)
async def test_local_errors(
    hass: HomeAssistant,
    mock_setup: tuple[AsyncMock, AsyncMock],
    exception: type[Exception],
    error: str,
) -> None:
    """Test we handle local API errors."""
    mock_login, _ = mock_setup
    mock_login.side_effect = exception

    result = await init_config_flow_local(hass, mock_setup)
    result2 = await complete_local_flow(hass, result, mock_setup)

    assert result2["type"] == FlowResultType.FORM
    assert result2["errors"] == {"base": error}

    # Test recovery from error
    mock_login.side_effect = None
    result3 = await complete_local_flow(hass, result, mock_setup)

    assert result3["type"] == FlowResultType.CREATE_ENTRY
    assert result3["title"] == TEST_HOST
    assert result3["data"] == {
        "host": TEST_HOST,
        "token": TEST_TOKEN,
        "verify_ssl": True,
        "hub": TEST_SERVER,
        "api_type": "local",
    }
    assert result3["result"].unique_id == TEST_GATEWAY_ID


@pytest.mark.parametrize(
    ("zeroconf_info", "expected_api_type"),
    [
        (FAKE_ZERO_CONF_INFO, "cloud"),
        (FAKE_ZERO_CONF_INFO_LOCAL, "local"),
    ],
)
async def test_zeroconf_discovery(
    hass: HomeAssistant,
    mock_setup: tuple[AsyncMock, AsyncMock],
    zeroconf_info: ZeroconfServiceInfo,
    expected_api_type: str,
) -> None:
    """Test zeroconf discovery for both cloud and local APIs."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=zeroconf_info,
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == config_entries.SOURCE_USER

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"hub": TEST_SERVER},
    )

    assert result2["type"] == FlowResultType.FORM
    assert result2["step_id"] == "local_or_cloud"

    result3 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"api_type": expected_api_type},
    )

    assert result3["type"] == FlowResultType.FORM
    assert result3["step_id"] == expected_api_type

    if expected_api_type == "cloud":
        result4 = await complete_cloud_flow(hass, result, mock_setup)
        expected_title = TEST_EMAIL
        expected_data = {
            "username": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "hub": TEST_SERVER,
            "api_type": "cloud",
        }
    else:
        result4 = await complete_local_flow(hass, result, mock_setup)
        expected_title = TEST_HOST
        expected_data = {
            "host": TEST_HOST,
            "token": TEST_TOKEN,
            "verify_ssl": True,
            "hub": TEST_SERVER,
            "api_type": "local",
        }

    assert result4["type"] == FlowResultType.CREATE_ENTRY
    assert result4["title"] == expected_title
    assert result4["data"] == expected_data
    assert result4["result"].unique_id == TEST_GATEWAY_ID


@pytest.mark.parametrize(
    ("api_type", "config_data"),
    [
        (
            "cloud",
            {
                "username": TEST_EMAIL,
                "password": TEST_PASSWORD,
                "hub": TEST_SERVER,
                "api_type": "cloud",
            },
        ),
        (
            "local",
            {
                "host": TEST_HOST,
                "token": TEST_TOKEN,
                "verify_ssl": True,
                "hub": TEST_SERVER,
                "api_type": "local",
            },
        ),
    ],
)
async def test_abort_on_duplicate_entry(
    hass: HomeAssistant,
    mock_setup: tuple[AsyncMock, AsyncMock],
    api_type: str,
    config_data: dict[str, Any],
) -> None:
    """Test we handle duplicate entries."""
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_GATEWAY_ID,
        data=config_data,
    ).add_to_hass(hass)

    # Start flow based on API type
    if api_type == "cloud":
        result = await init_config_flow_cloud(hass, mock_setup)
        result3 = await complete_cloud_flow(hass, result, mock_setup)
    else:
        result = await init_config_flow_local(hass, mock_setup)
        result3 = await complete_local_flow(hass, result, mock_setup)

    assert result3["type"] == FlowResultType.ABORT
    assert result3["reason"] == "already_configured"
