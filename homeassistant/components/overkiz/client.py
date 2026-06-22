"""Factories for the Overkiz client."""

from pyoverkiz.auth.credentials import (
    LocalTokenCredentials,
    UsernamePasswordCredentials,
)
from pyoverkiz.client import OverkizClient
from pyoverkiz.enums import Server
from pyoverkiz.utils import create_local_server_config

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession


def create_local_client(
    hass: HomeAssistant, host: str, token: str, verify_ssl: bool
) -> OverkizClient:
    """Create Overkiz local client."""
    session = async_create_clientsession(hass, verify_ssl=verify_ssl)

    return OverkizClient(
        server=create_local_server_config(host=host),
        credentials=LocalTokenCredentials(token),
        session=session,
        verify_ssl=verify_ssl,
    )


def create_cloud_client(
    hass: HomeAssistant, username: str, password: str, server: Server
) -> OverkizClient:
    """Create Overkiz cloud client."""
    # To allow users with multiple accounts/hubs, we create a
    # new session so they have separate cookies
    session = async_create_clientsession(hass)

    return OverkizClient(
        server=server,
        credentials=UsernamePasswordCredentials(username, password),
        session=session,
    )
