# Copyright (c) 2026 Harper Reed
# ABOUTME: Handles Gentex PLACE account setup, MFA, duplicate checks, and reauth.
# ABOUTME: Persists only username, refresh token, and stable Cognito account identity.
"""Config flow for the Gentex PLACE integration."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypeVar, override

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from place import (
    CognitoAuth,
    MfaRequired,
    PlaceAuthError,
    PlaceClient,
    PlaceDiscoveryError,
    PlaceInvalidAuthError,
    PlaceTimeoutError,
)

from . import auth as auth_helpers
from .auth import MemoryTokenCache
from .const import CONF_ACCOUNT_ID, CONF_REFRESH_TOKEN, DOMAIN, safe_entry_title

if TYPE_CHECKING:
    from collections.abc import Awaitable, Mapping

_T = TypeVar("_T")

_ABORT_ALREADY_CONFIGURED = "already_configured"
_ABORT_WRONG_ACCOUNT = "wrong_account"

USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})
MFA_SCHEMA = vol.Schema({vol.Required("mfa_code"): str})


class _FlowDataError(Exception):
    """Signal invalid data at a successful SDK boundary."""


class _KnownIdentityAbortError(Exception):
    """Signal a flow outcome decided by the stable account identity."""

    def __init__(self, reason: str) -> None:
        """Store the safe Home Assistant abort reason."""
        self.reason = reason


class GentexPlaceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Gentex PLACE config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Create flow-local authentication state."""
        self._auth: CognitoAuth | None = None
        self._client: PlaceClient | None = None
        self._username: str | None = None
        self._token_cache = MemoryTokenCache()
        self._reauth_entry: config_entries.ConfigEntry | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect account credentials and validate the account."""
        if user_input is None:
            return self._show_user_form()

        username = user_input[CONF_USERNAME]
        password = user_input[CONF_PASSWORD]
        auth = self._start_login(username)
        try:
            await self._async_await_sdk(auth.authenticate(username, password))
        except MfaRequired:
            return self._show_mfa_form()
        except PlaceInvalidAuthError:
            self._clear_flow_state()
            return self._show_user_form("invalid_auth")
        except PlaceTimeoutError, TimeoutError, PlaceAuthError:
            self._clear_flow_state()
            return self._show_user_form("cannot_connect")
        except Exception:
            self._clear_flow_state()
            raise
        return await self._async_finish_login(error_step="user")

    async def async_step_mfa(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Complete a pending Cognito MFA challenge."""
        if user_input is None:
            return self._show_mfa_form()
        if self._auth is None:
            self._clear_flow_state()
            if self.source == config_entries.SOURCE_REAUTH:
                entry = self._get_reauth_entry()
                username = entry.data.get(CONF_USERNAME)
                if isinstance(username, str) and username:
                    self._reauth_entry = entry
                    return self._show_reauth_form(username)
            return self._show_user_form("invalid_auth")

        try:
            await self._async_await_sdk(self._auth.submit_mfa(user_input["mfa_code"]))
        except PlaceInvalidAuthError:
            return self._show_mfa_form("invalid_mfa")
        except PlaceTimeoutError, TimeoutError, PlaceAuthError:
            return self._show_mfa_form("cannot_connect")
        except Exception:
            self._clear_flow_state()
            raise

        error_step = "reauth_confirm" if self._reauth_entry is not None else "user"
        return await self._async_finish_login(error_step=error_step)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Start reauthentication for the linked config entry."""
        del entry_data
        self._reauth_entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect the password for the existing account."""
        entry = self._reauth_entry or self._get_reauth_entry()
        self._reauth_entry = entry
        username = entry.data.get(CONF_USERNAME)
        if not isinstance(username, str) or not username:
            self._clear_flow_state()
            return self.async_abort(reason="wrong_account")
        if user_input is None:
            return self._show_reauth_form(username)

        auth = self._start_login(username, reauth_entry=entry)
        password = user_input[CONF_PASSWORD]
        try:
            await self._async_await_sdk(auth.authenticate(username, password))
        except MfaRequired:
            return self._show_mfa_form()
        except PlaceInvalidAuthError:
            self._clear_flow_state(keep_reauth=True)
            return self._show_reauth_form(username, "invalid_auth")
        except PlaceTimeoutError, TimeoutError, PlaceAuthError:
            self._clear_flow_state(keep_reauth=True)
            return self._show_reauth_form(username, "cannot_connect")
        except Exception:
            self._clear_flow_state()
            raise
        return await self._async_finish_login(error_step="reauth_confirm")

    def _start_login(
        self,
        username: str,
        *,
        reauth_entry: config_entries.ConfigEntry | None = None,
    ) -> CognitoAuth:
        """Create fresh flow-local SDK objects for one login attempt."""
        self._clear_flow_state()
        self._username = username
        self._reauth_entry = reauth_entry
        self._auth = auth_helpers.create_auth(self.hass, self._token_cache)
        self._client = auth_helpers.create_client(self._auth)
        return self._auth

    async def _async_finish_login(
        self, *, error_step: str
    ) -> config_entries.ConfigFlowResult:
        """Validate identity, discovery, and cached durable token data."""
        try:
            username, identity_id, refresh_token = await self._async_validate_account()
        except _KnownIdentityAbortError as err:
            self._clear_flow_state()
            return self.async_abort(reason=err.reason)
        except PlaceInvalidAuthError:
            return self._finish_error(error_step, "invalid_auth")
        except _NoDevicesError:
            return self._finish_error(error_step, "no_devices")
        except PlaceAuthError, PlaceDiscoveryError, _FlowDataError:
            return self._finish_error(error_step, "cannot_connect")
        except Exception:
            self._clear_flow_state()
            raise

        reauth_entry = self._reauth_entry
        try:
            await self.async_set_unique_id(identity_id)
            if reauth_entry is not None:
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_REFRESH_TOKEN: refresh_token},
                )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=safe_entry_title(
                    entry.title
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                ),
                data={
                    CONF_USERNAME: username,
                    CONF_REFRESH_TOKEN: refresh_token,
                    CONF_ACCOUNT_ID: identity_id,
                },
            )
        finally:
            self._clear_flow_state()

    async def _async_validate_account(self) -> tuple[str, str, str]:
        """Return a stable account identity and matching cached refresh token."""
        if self._auth is None or self._client is None or self._username is None:
            raise _FlowDataError

        credentials = await self._async_await_network(
            self._auth.async_get_iot_credentials()
        )
        identity_id = credentials.identity_id
        if not isinstance(identity_id, str) or not identity_id:
            raise _FlowDataError

        if self._reauth_entry is not None:
            if self._reauth_entry.unique_id != identity_id:
                raise _KnownIdentityAbortError(_ABORT_WRONG_ACCOUNT)
        elif (
            self.hass.config_entries.async_entry_for_domain_unique_id(
                DOMAIN, identity_id
            )
            is not None
        ):
            raise _KnownIdentityAbortError(_ABORT_ALREADY_CONFIGURED)

        devices = await self._async_await_network(self._client.async_discover())
        if not devices:
            raise _NoDevicesError

        token_data = self._token_cache.load()
        if token_data is None or token_data.get(CONF_USERNAME) != self._username:
            raise _FlowDataError
        refresh_token = token_data.get(CONF_REFRESH_TOKEN)
        if not isinstance(refresh_token, str) or not refresh_token:
            raise _FlowDataError
        return self._username, identity_id, refresh_token

    def _finish_error(
        self, step_id: str, error: str
    ) -> config_entries.ConfigFlowResult:
        """Clear SDK state and return the appropriate login form."""
        username = self._username
        reauth_entry = self._reauth_entry
        self._clear_flow_state(keep_reauth=reauth_entry is not None)
        if step_id == "reauth_confirm" and username is not None:
            return self._show_reauth_form(username, error)
        return self._show_user_form(error)

    async def _async_await_sdk(self, operation: Awaitable[_T]) -> _T:
        """Clear all flow state when an SDK await receives cancellation."""
        try:
            return await operation
        except asyncio.CancelledError:
            self._clear_flow_state()
            raise

    async def _async_await_network(self, operation: Awaitable[_T]) -> _T:
        """Map timeouts only at a known SDK network await boundary."""
        try:
            return await self._async_await_sdk(operation)
        except PlaceTimeoutError, TimeoutError:
            raise _FlowConnectionError from None

    def _clear_flow_state(self, *, keep_reauth: bool = False) -> None:
        """Drop all flow-owned SDK, account, and token state."""
        self._token_cache.clear()
        self._auth = None
        self._client = None
        self._username = None
        if not keep_reauth:
            self._reauth_entry = None

    @callback
    @override
    def async_remove(self) -> None:
        """Release flow-owned secrets and SDK references when HA removes the flow."""
        self._clear_flow_state()

    def _show_user_form(
        self, error: str | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the initial account form."""
        return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            errors={"base": error} if error else {},
        )

    def _show_mfa_form(
        self, error: str | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the MFA challenge form."""
        return self.async_show_form(
            step_id="mfa",
            data_schema=MFA_SCHEMA,
            errors={"base": error} if error else {},
        )

    def _show_reauth_form(
        self, username: str, error: str | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the password-only reauthentication form."""
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors={"base": error} if error else {},
            description_placeholders={CONF_USERNAME: username},
        )


class _NoDevicesError(_FlowDataError):
    """Signal successful authentication for an account with no PLACE devices."""


class _FlowConnectionError(_FlowDataError):
    """Signal a retryable failure at a known SDK network await boundary."""
