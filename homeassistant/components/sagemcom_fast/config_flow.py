"""Config flow for Sagemcom integration."""
import logging

from aiohttp import ClientError
from sagemcom_api.client import SagemcomClient
from sagemcom_api.enums import EncryptionMethod
from sagemcom_api.exceptions import (
    AccessRestrictionException,
    AuthenticationException,
    LoginTimeoutException,
)
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.dhcp import IP_ADDRESS
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback

from .const import CONF_ENCRYPTION_METHOD, DOMAIN
from .options_flow import OptionsFlow

_LOGGER = logging.getLogger(__name__)

ENCRYPTION_METHODS = [item.value for item in EncryptionMethod]

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Required(CONF_ENCRYPTION_METHOD): vol.In(ENCRYPTION_METHODS),
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sagemcom F@st."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize the Sagemcom F@st config flow."""
        self.discovery_schema = {}

    async def async_validate_input(self, user_input):
        """Validate user credentials."""
        username = user_input.get(CONF_USERNAME) or ""
        password = user_input.get(CONF_PASSWORD) or ""
        host = user_input.get(CONF_HOST)
        encryption_method = user_input.get(CONF_ENCRYPTION_METHOD)

        async with SagemcomClient(
            host, username, password, EncryptionMethod(encryption_method)
        ) as client:
            await client.login()
            return self.async_create_entry(
                title=host,
                data=user_input,
            )

    async def async_step_dhcp(self, discovery_info: dict):
        """Prepare configuration for a DHCP discovered Sagemcom F@st router."""
        await self.async_set_unique_id(discovery_info[IP_ADDRESS])
        self._abort_if_unique_id_configured()

        self.discovery_schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=discovery_info[IP_ADDRESS]): str,
                vol.Optional(CONF_USERNAME): str,
                vol.Optional(CONF_PASSWORD): str,
                vol.Required(CONF_ENCRYPTION_METHOD): vol.In(ENCRYPTION_METHODS),
            }
        )

        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input:
            await self.async_set_unique_id(user_input.get(CONF_HOST))
            self._abort_if_unique_id_configured()

            try:
                return await self.async_validate_input(user_input)
            except AccessRestrictionException:
                errors["base"] = "access_restricted"
            except AuthenticationException:
                errors["base"] = "invalid_auth"
            except (TimeoutError, ClientError):
                errors["base"] = "cannot_connect"
            except LoginTimeoutException:
                errors["base"] = "login_timeout"
            except Exception as exception:  # pylint: disable=broad-except
                errors["base"] = "unknown"
                _LOGGER.exception(exception)

        data_schema = self.discovery_schema or DATA_SCHEMA

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow for this handler."""
        return OptionsFlow(config_entry)
