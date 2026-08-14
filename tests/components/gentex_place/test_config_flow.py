# Copyright (c) 2026 Gentex
# ABOUTME: Verifies PLACE setup, MFA, duplicate-account, error, and reauth flows.
# ABOUTME: Tests use public SDK fakes and assert secrets never enter flow results.
"""Tests for the Gentex PLACE config flow."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from place import (
    MfaRequired,
    PlaceAuthError,
    PlaceDiscoveryError,
    PlaceInvalidAuthError,
    PlaceTimeoutError,
    PlaceTransientAuthError,
)
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    start_reauth_flow,
)

from custom_components.gentex_place.config_flow import GentexPlaceConfigFlow
from custom_components.gentex_place.const import (
    CONF_ACCOUNT_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)
from tests.components.gentex_place.fakes import (
    AuthenticationCall,
    CancellationBlocker,
    MfaCall,
    install_place_fakes,
    invalid_credentials,
    make_credentials,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult
    from homeassistant.core import HomeAssistant
    from place import DiscoverDevice

PASSWORD = "PASSWORD-CANARY"
MFA_CODE = "MFA-CANARY"
RETRY_ATTEMPT_COUNT = 2
SAFE_ENTRY_DATA = {
    CONF_USERNAME: "alice",
    CONF_REFRESH_TOKEN: "refresh-1",
    CONF_ACCOUNT_ID: "identity-1",
}
SECRET_CANARIES = (
    PASSWORD,
    MFA_CODE,
    "MFA-RETRY-CANARY",
    "SESSION-CANARY",
    "ID-TOKEN-CANARY",
    "AWS-ACCESS-CANARY",
    "AWS-SECRET-CANARY",
    "AWS-SESSION-CANARY",
    "REMOVAL-TOKEN-CANARY",
)


def _capture_next_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> list[GentexPlaceConfigFlow]:
    """Capture integration flow instances without touching HA manager internals."""
    flows: list[GentexPlaceConfigFlow] = []
    original_init = GentexPlaceConfigFlow.__init__

    def capture_init(flow: GentexPlaceConfigFlow) -> None:
        original_init(flow)
        flows.append(flow)

    monkeypatch.setattr(GentexPlaceConfigFlow, "__init__", capture_init)
    return flows


def _assert_flow_state_cleared(flow: GentexPlaceConfigFlow) -> None:
    """Assert all integration-owned live state has been released."""
    state = vars(flow)
    assert state.get("_auth") is None
    assert state.get("_client") is None
    assert state.get("_username") is None
    assert state.get("_reauth_entry") is None
    assert "_password" not in state
    token_cache = state["_token_cache"]
    assert token_cache.load() is None
    assert all(secret not in repr(state) for secret in SECRET_CANARIES)


async def _cancel_configure(
    hass: HomeAssistant,
    flow_id: str,
    user_input: dict[str, str],
    blocker: CancellationBlocker,
) -> None:
    """Cancel one flow submission only after its fake SDK await is active."""
    task = asyncio.create_task(
        hass.config_entries.flow.async_configure(flow_id, user_input)
    )
    await blocker.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _start_user_flow(hass: HomeAssistant) -> ConfigFlowResult:
    """Start setup and return its user form."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _submit_user(
    hass: HomeAssistant,
    flow_id: str,
    *,
    username: str = "alice",
    password: str = PASSWORD,
) -> ConfigFlowResult:
    """Submit username and password to a live flow."""
    return await hass.config_entries.flow.async_configure(
        flow_id, {CONF_USERNAME: username, CONF_PASSWORD: password}
    )


async def _submit_mfa(
    hass: HomeAssistant, flow_id: str, code: str = MFA_CODE
) -> ConfigFlowResult:
    """Submit an MFA code to a live flow."""
    return await hass.config_entries.flow.async_configure(flow_id, {"mfa_code": code})


def _assert_no_secrets(value: object, caplog: pytest.LogCaptureFixture) -> None:
    """Assert neither a result nor captured logs expose secret canaries."""
    output = f"{value!r}\n{caplog.text}"
    assert all(secret not in output for secret in SECRET_CANARIES)


def _assert_form(result: ConfigFlowResult, step_id: str, error: str) -> None:
    """Assert an exact base-error form result."""
    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == step_id
    assert result.get("errors") == {"base": error}


def _reauth_entry(
    hass: HomeAssistant,
    *,
    unique_id: str = "identity-1",
    data: dict[str, Any] | None = None,
) -> MockConfigEntry:
    """Add an existing PLACE entry for reauthentication tests."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Alice's PLACE",
        unique_id=unique_id,
        data=data
        or {
            CONF_USERNAME: "alice",
            CONF_REFRESH_TOKEN: "refresh-old",
            CONF_ACCOUNT_ID: "identity-1",
            "preserved": "value",
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_user_flow_stores_only_allowlisted_account_data(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = install_place_fakes(monkeypatch)
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("title") == "alice"
    assert result.get("data") == SAFE_ENTRY_DATA
    assert harness.auth is not None
    assert harness.auth.authenticate_calls == [
        AuthenticationCall.from_values("alice", PASSWORD)
    ]
    assert harness.auth.credential_calls == 1
    assert harness.client is not None
    assert harness.client.discover_calls == 1
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)


async def test_mfa_challenge_shows_mfa_form_without_using_post_auth_calls(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    challenge = MfaRequired(
        challenge_name="SOFTWARE_TOKEN_MFA", session="SESSION-CANARY", username="alice"
    )
    harness = install_place_fakes(monkeypatch, authenticate_results=[challenge])
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == "mfa"
    assert harness.auth is not None
    assert harness.auth.credential_calls == 0
    assert harness.client is not None
    assert harness.client.discover_calls == 0
    _assert_no_secrets(result, caplog)


async def test_invalid_mfa_code_returns_same_form_without_discovery(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SMS_MFA", session="SESSION-CANARY", username="alice"
            )
        ],
        mfa_results=[PlaceInvalidAuthError("bad MFA")],
    )
    form = await _start_user_flow(hass)
    mfa_form = await _submit_user(hass, form["flow_id"])

    result = await _submit_mfa(hass, mfa_form["flow_id"])

    _assert_form(result, "mfa", "invalid_mfa")
    assert harness.auth is not None
    assert harness.auth.mfa_calls == [MfaCall.from_value(MFA_CODE)]
    assert harness.auth.credential_calls == 0
    assert harness.client is not None
    assert harness.client.discover_calls == 0
    _assert_no_secrets(result, caplog)


async def test_valid_mfa_creates_entry_without_password_or_code(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SOFTWARE_TOKEN_MFA",
                session="SESSION-CANARY",
                username="alice",
            )
        ],
    )
    form = await _start_user_flow(hass)
    mfa_form = await _submit_user(hass, form["flow_id"])

    result = await _submit_mfa(hass, mfa_form["flow_id"])

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("data") == SAFE_ENTRY_DATA
    assert harness.auth is not None
    assert harness.auth.mfa_calls == [MfaCall.from_value(MFA_CODE)]
    assert harness.auth.credential_calls == 1
    assert harness.client is not None
    assert harness.client.discover_calls == 1
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)


@pytest.mark.parametrize(
    "discover_result", [[], PlaceDiscoveryError("AWS-ACCESS-CANARY")]
)
async def test_duplicate_account_aborts_before_discovery(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    discover_result: list[DiscoverDevice] | BaseException,
) -> None:
    existing = _reauth_entry(hass)
    harness = install_place_fakes(monkeypatch, discover_results=[discover_result])
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"], username="alias")

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "already_configured"
    assert hass.config_entries.async_entries(DOMAIN) == [existing]
    assert harness.auth is not None
    assert harness.auth.credential_calls == 1
    assert harness.client is not None
    assert harness.client.discover_calls == 0
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None


@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        (PlaceInvalidAuthError("PASSWORD-CANARY"), "invalid_auth"),
        (PlaceTransientAuthError("PASSWORD-CANARY"), "cannot_connect"),
    ],
)
async def test_login_errors_return_user_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: BaseException,
    expected_error: str,
) -> None:
    harness = install_place_fakes(monkeypatch, authenticate_results=[error])
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    _assert_form(result, "user", expected_error)
    assert harness.auth is not None
    assert harness.auth.credential_calls == 0
    assert harness.client is not None
    assert harness.client.discover_calls == 0
    _assert_no_secrets(result, caplog)


async def test_invalid_login_retry_consumes_next_factory_script(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[PlaceInvalidAuthError("invalid"), None],
    )
    form = await _start_user_flow(hass)
    retry_form = await _submit_user(hass, form["flow_id"])

    result = await _submit_user(hass, retry_form["flow_id"])

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("data") == SAFE_ENTRY_DATA
    assert len(harness.auth_instances) == RETRY_ATTEMPT_COUNT
    assert [auth.authenticate_calls for auth in harness.auth_instances] == [
        [AuthenticationCall.from_values("alice", PASSWORD)],
        [AuthenticationCall.from_values("alice", PASSWORD)],
    ]


@pytest.mark.parametrize("stage", ["authenticate", "credentials", "discovery"])
async def test_base_auth_error_returns_retryable_user_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
) -> None:
    error = PlaceAuthError("ID-TOKEN-CANARY")
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[error] if stage == "authenticate" else None,
        credential_results=[error] if stage == "credentials" else None,
        discover_results=[error] if stage == "discovery" else None,
    )
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    _assert_form(result, "user", "cannot_connect")
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)


async def test_base_auth_error_during_mfa_keeps_retry_form_without_secrets(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SMS_MFA", session="SESSION-CANARY", username="alice"
            )
        ],
        mfa_results=[PlaceAuthError("AWS-SESSION-CANARY")],
    )
    form = await _start_user_flow(hass)
    mfa_form = await _submit_user(hass, form["flow_id"])

    result = await _submit_mfa(hass, mfa_form["flow_id"])

    _assert_form(result, "mfa", "cannot_connect")
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert harness.auth is not None
    assert harness.auth.mfa_calls == [MfaCall.from_value(MFA_CODE)]
    assert harness.auth.credential_calls == 0
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)

    retry_result = await _submit_mfa(hass, result["flow_id"], "MFA-RETRY-CANARY")

    assert retry_result.get("type") is FlowResultType.CREATE_ENTRY
    assert retry_result.get("data") == SAFE_ENTRY_DATA
    assert harness.token_cache.load() is None
    _assert_no_secrets(retry_result, caplog)


@pytest.mark.parametrize("error_type", [PlaceTimeoutError, TimeoutError])
@pytest.mark.parametrize("stage", ["authenticate", "credentials", "discovery"])
async def test_timeout_at_network_await_returns_user_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
    error_type: type[BaseException],
) -> None:
    error = error_type("ID-TOKEN-CANARY")
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[error] if stage == "authenticate" else None,
        credential_results=[error] if stage == "credentials" else None,
        discover_results=[error] if stage == "discovery" else None,
    )
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    _assert_form(result, "user", "cannot_connect")
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)


@pytest.mark.parametrize("error_type", [PlaceTimeoutError, TimeoutError])
async def test_timeout_during_mfa_keeps_mfa_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error_type: type[BaseException],
) -> None:
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SMS_MFA", session="SESSION-CANARY", username="alice"
            )
        ],
        mfa_results=[error_type("AWS-SESSION-CANARY")],
    )
    form = await _start_user_flow(hass)
    mfa_form = await _submit_user(hass, form["flow_id"])

    result = await _submit_mfa(hass, mfa_form["flow_id"])

    _assert_form(result, "mfa", "cannot_connect")
    assert harness.auth is not None
    assert harness.auth.credential_calls == 0
    _assert_no_secrets(result, caplog)


@pytest.mark.parametrize("error_type", [PlaceTimeoutError, TimeoutError])
@pytest.mark.parametrize("stage", ["authenticate", "credentials", "discovery"])
async def test_timeout_at_network_await_returns_reauth_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
    error_type: type[BaseException],
) -> None:
    entry = _reauth_entry(hass)
    old_data = dict(entry.data)
    error = error_type("ID-TOKEN-CANARY")
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[error] if stage == "authenticate" else None,
        credential_results=[error] if stage == "credentials" else None,
        discover_results=[error] if stage == "discovery" else None,
    )
    form = await start_reauth_flow(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    _assert_form(result, "reauth_confirm", "cannot_connect")
    assert entry.data == old_data
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)


@pytest.mark.parametrize("error_type", [PlaceTimeoutError, TimeoutError])
@pytest.mark.parametrize("stage", ["credentials", "discovery"])
async def test_timeout_after_reauth_mfa_returns_reauth_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
    error_type: type[BaseException],
) -> None:
    entry = _reauth_entry(hass)
    old_data = dict(entry.data)
    error = error_type("AWS-SESSION-CANARY")
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SOFTWARE_TOKEN_MFA",
                session="SESSION-CANARY",
                username="alice",
            )
        ],
        credential_results=[error] if stage == "credentials" else None,
        discover_results=[error] if stage == "discovery" else None,
    )
    form = await start_reauth_flow(hass, entry)
    mfa_form = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    result = await _submit_mfa(hass, mfa_form["flow_id"])

    _assert_form(result, "reauth_confirm", "cannot_connect")
    assert entry.data == old_data
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)


@pytest.mark.parametrize(
    ("credential_error", "expected_error"),
    [
        (PlaceInvalidAuthError("AWS-ACCESS-CANARY"), "invalid_auth"),
        (PlaceTransientAuthError("AWS-ACCESS-CANARY"), "cannot_connect"),
    ],
)
async def test_credential_errors_map_to_typed_user_errors(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    credential_error: BaseException,
    expected_error: str,
) -> None:
    harness = install_place_fakes(monkeypatch, credential_results=[credential_error])
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    _assert_form(result, "user", expected_error)
    assert harness.auth is not None
    assert harness.auth.credential_calls == 1
    assert harness.client is not None
    assert harness.client.discover_calls == 0
    _assert_no_secrets(result, caplog)


@pytest.mark.parametrize(
    ("discovery_error", "expected_error"),
    [
        (PlaceInvalidAuthError("AWS-ACCESS-CANARY"), "invalid_auth"),
        (PlaceTransientAuthError("AWS-ACCESS-CANARY"), "cannot_connect"),
        (PlaceDiscoveryError("AWS-ACCESS-CANARY"), "cannot_connect"),
    ],
)
async def test_discovery_errors_map_to_typed_user_errors(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    discovery_error: BaseException,
    expected_error: str,
) -> None:
    harness = install_place_fakes(monkeypatch, discover_results=[discovery_error])
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    _assert_form(result, "user", expected_error)
    assert harness.auth is not None
    assert harness.auth.credential_calls == 1
    assert harness.client is not None
    assert harness.client.discover_calls == 1
    _assert_no_secrets(result, caplog)


async def test_empty_discovery_returns_no_devices(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = install_place_fakes(monkeypatch, discover_results=[[]])
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    _assert_form(result, "user", "no_devices")
    assert harness.client is not None
    assert harness.client.discover_calls == 1


async def test_no_devices_retry_can_use_a_different_account(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = install_place_fakes(
        monkeypatch,
        credential_results=[
            make_credentials("identity-1"),
            make_credentials("identity-2"),
        ],
        discover_results=[[]],
    )
    form = await _start_user_flow(hass)
    retry_form = await _submit_user(hass, form["flow_id"])

    result = await _submit_user(
        hass, retry_form["flow_id"], username="different-account"
    )

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("title") == "different-account"
    assert result.get("data") == {
        **SAFE_ENTRY_DATA,
        CONF_USERNAME: "different-account",
        CONF_ACCOUNT_ID: "identity-2",
    }
    assert len(harness.auth_instances) == RETRY_ATTEMPT_COUNT
    assert len(harness.client_instances) == RETRY_ATTEMPT_COUNT


@pytest.mark.parametrize("identity_id", ["", None, 42])
async def test_invalid_account_identity_returns_cannot_connect(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, identity_id: object
) -> None:
    install_place_fakes(
        monkeypatch, credential_results=[invalid_credentials(identity_id)]
    )
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    _assert_form(result, "user", "cannot_connect")


async def test_missing_cached_refresh_token_returns_cannot_connect(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_place_fakes(monkeypatch, save_token=False)
    form = await _start_user_flow(hass)

    result = await _submit_user(hass, form["flow_id"])

    _assert_form(result, "user", "cannot_connect")


async def test_unexpected_programmer_error_propagates(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = install_place_fakes(
        monkeypatch, discover_results=[RuntimeError("programmer bug")]
    )
    form = await _start_user_flow(hass)

    with pytest.raises(RuntimeError, match="programmer bug"):
        await _submit_user(hass, form["flow_id"])
    assert harness.auth is not None
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None


async def test_programmer_timeout_outside_sdk_await_propagates(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    message = "programmer timeout"

    async def raise_programmer_timeout(
        _flow: GentexPlaceConfigFlow,
    ) -> tuple[str, str, str]:
        raise TimeoutError(message)

    harness = install_place_fakes(monkeypatch)
    monkeypatch.setattr(
        GentexPlaceConfigFlow,
        "_async_validate_account",
        raise_programmer_timeout,
    )
    form = await _start_user_flow(hass)

    with pytest.raises(TimeoutError, match=message):
        await _submit_user(hass, form["flow_id"])

    assert harness.token_cache is not None
    assert harness.token_cache.load() is None


async def test_reauth_success_updates_only_refresh_token_and_reloads(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _reauth_entry(hass)
    harness = install_place_fakes(monkeypatch)
    form = await start_reauth_flow(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "reauth_successful"
    assert entry.data == {
        CONF_USERNAME: "alice",
        CONF_REFRESH_TOKEN: "refresh-1",
        CONF_ACCOUNT_ID: "identity-1",
        "preserved": "value",
    }
    assert entry.unique_id == "identity-1"
    assert harness.auth is not None
    assert harness.auth.authenticate_calls == [
        AuthenticationCall.from_values("alice", PASSWORD)
    ]
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None


@pytest.mark.parametrize(
    "discover_result", [[], PlaceDiscoveryError("AWS-ACCESS-CANARY")]
)
async def test_reauth_rejects_different_identity_before_discovery(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    discover_result: list[DiscoverDevice] | BaseException,
) -> None:
    entry = _reauth_entry(hass)
    old_data = dict(entry.data)
    harness = install_place_fakes(
        monkeypatch,
        credential_results=[make_credentials("identity-2")],
        discover_results=[discover_result],
    )
    form = await start_reauth_flow(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "wrong_account"
    assert entry.data == old_data
    assert entry.unique_id == "identity-1"
    assert harness.client is not None
    assert harness.client.discover_calls == 0
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None


async def test_reauth_uses_stored_username_not_supplied_entry_data(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _reauth_entry(hass)
    harness = install_place_fakes(monkeypatch)

    form = await start_reauth_flow(
        hass, entry, data={CONF_USERNAME: "mallory", CONF_REFRESH_TOKEN: "attacker"}
    )
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    assert result.get("reason") == "reauth_successful"
    assert harness.auth is not None
    assert harness.auth.authenticate_calls == [
        AuthenticationCall.from_values("alice", PASSWORD)
    ]
    assert entry.data[CONF_USERNAME] == "alice"
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None


async def test_reauth_mfa_updates_existing_entry_instead_of_creating_one(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _reauth_entry(hass)
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SOFTWARE_TOKEN_MFA",
                session="SESSION-CANARY",
                username="alice",
            )
        ],
    )
    form = await start_reauth_flow(hass, entry)
    mfa_form = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    result = await _submit_mfa(hass, mfa_form["flow_id"])

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "reauth_successful"
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert entry.data[CONF_REFRESH_TOKEN] == "refresh-1"
    assert harness.auth is not None
    assert harness.auth.mfa_calls == [MfaCall.from_value(MFA_CODE)]
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None


async def test_reauth_mfa_post_auth_error_returns_reauth_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = _reauth_entry(hass)
    old_data = dict(entry.data)
    install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SOFTWARE_TOKEN_MFA",
                session="SESSION-CANARY",
                username="alice",
            )
        ],
        credential_results=[PlaceTransientAuthError("temporary")],
    )
    form = await start_reauth_flow(hass, entry)
    mfa_form = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    result = await _submit_mfa(hass, mfa_form["flow_id"])

    _assert_form(result, "reauth_confirm", "cannot_connect")
    assert entry.data == old_data


async def test_invalid_mfa_retry_is_idempotent(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SMS_MFA", session="SESSION-CANARY", username="alice"
            )
        ],
        mfa_results=[PlaceInvalidAuthError("bad"), None],
    )
    form = await _start_user_flow(hass)
    mfa_form = await _submit_user(hass, form["flow_id"])
    retry_form = await _submit_mfa(hass, mfa_form["flow_id"], "wrong")

    result = await _submit_mfa(hass, retry_form["flow_id"], "correct")

    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert result.get("data") == SAFE_ENTRY_DATA
    assert harness.auth is not None
    assert len(harness.auth.mfa_calls) == len(("wrong", "correct"))
    assert harness.auth.credential_calls == 1
    assert harness.client is not None
    assert harness.client.discover_calls == 1
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None


async def test_user_schema_error_does_not_create_sdk_objects(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = install_place_fakes(monkeypatch)
    form = await _start_user_flow(hass)

    with pytest.raises(InvalidData, match="Schema validation failed"):
        await hass.config_entries.flow.async_configure(
            form["flow_id"], {CONF_USERNAME: "alice"}
        )

    assert harness.auth is None
    assert harness.client is None


async def test_mfa_schema_error_does_not_submit_or_discover(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SMS_MFA", session="SESSION-CANARY", username="alice"
            )
        ],
    )
    form = await _start_user_flow(hass)
    mfa_form = await _submit_user(hass, form["flow_id"])

    with pytest.raises(InvalidData, match="Schema validation failed"):
        await hass.config_entries.flow.async_configure(mfa_form["flow_id"], {})

    assert harness.auth is not None
    assert harness.auth.mfa_calls == []
    assert harness.auth.credential_calls == 0
    assert harness.client is not None
    assert harness.client.discover_calls == 0


@pytest.mark.parametrize(
    "source", [config_entries.SOURCE_USER, config_entries.SOURCE_REAUTH]
)
@pytest.mark.parametrize("stage", ["authenticate", "credentials", "discovery"])
async def test_cancellation_clears_flow_state_at_network_awaits(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    source: str,
    stage: str,
) -> None:
    flows = _capture_next_flow(monkeypatch)
    blocker = CancellationBlocker()
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[blocker] if stage == "authenticate" else None,
        credential_results=[blocker] if stage == "credentials" else None,
        discover_results=[blocker] if stage == "discovery" else None,
    )
    entry = _reauth_entry(hass) if source == config_entries.SOURCE_REAUTH else None
    old_data = dict(entry.data) if entry is not None else None
    form = (
        await start_reauth_flow(hass, entry)
        if entry is not None
        else await _start_user_flow(hass)
    )
    user_input = (
        {CONF_PASSWORD: PASSWORD}
        if entry is not None
        else {CONF_USERNAME: "alice", CONF_PASSWORD: PASSWORD}
    )

    await _cancel_configure(hass, form["flow_id"], user_input, blocker)

    assert len(flows) == 1
    _assert_flow_state_cleared(flows[0])
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    if entry is None:
        assert hass.config_entries.async_entries(DOMAIN) == []
    else:
        assert entry.data == old_data
    assert all(secret not in caplog.text for secret in SECRET_CANARIES)
    hass.config_entries.flow.async_abort(form["flow_id"])


@pytest.mark.parametrize(
    ("source", "expected_step"),
    [
        (config_entries.SOURCE_USER, "user"),
        (config_entries.SOURCE_REAUTH, "reauth_confirm"),
    ],
)
async def test_cancelled_mfa_lost_state_returns_to_source_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    expected_step: str,
) -> None:
    flows = _capture_next_flow(monkeypatch)
    blocker = CancellationBlocker()
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SMS_MFA", session="SESSION-CANARY", username="alice"
            )
        ],
        mfa_results=[blocker],
    )
    entry = _reauth_entry(hass) if source == config_entries.SOURCE_REAUTH else None
    old_data = dict(entry.data) if entry is not None else None
    form = (
        await start_reauth_flow(hass, entry)
        if entry is not None
        else await _start_user_flow(hass)
    )
    mfa_form = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        {CONF_PASSWORD: PASSWORD}
        if entry is not None
        else {CONF_USERNAME: "alice", CONF_PASSWORD: PASSWORD},
    )

    await _cancel_configure(hass, mfa_form["flow_id"], {"mfa_code": MFA_CODE}, blocker)
    assert len(flows) == 1
    _assert_flow_state_cleared(flows[0])
    result = await _submit_mfa(hass, mfa_form["flow_id"])

    assert result.get("type") is FlowResultType.FORM
    assert result.get("step_id") == expected_step
    assert harness.auth is not None
    assert len(harness.auth.mfa_calls) == 1
    if entry is not None:
        assert entry.data == old_data
    hass.config_entries.flow.async_abort(result["flow_id"])


async def test_public_flow_removal_clears_active_mfa_state(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    flows = _capture_next_flow(monkeypatch)
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SOFTWARE_TOKEN_MFA",
                session="SESSION-CANARY",
                username="alice",
            )
        ],
    )
    form = await _start_user_flow(hass)
    mfa_form = await _submit_user(hass, form["flow_id"])
    assert harness.token_cache is not None
    harness.token_cache.save(
        {CONF_USERNAME: "alice", CONF_REFRESH_TOKEN: "REMOVAL-TOKEN-CANARY"}
    )

    hass.config_entries.flow.async_abort(mfa_form["flow_id"])

    assert len(flows) == 1
    _assert_flow_state_cleared(flows[0])


async def test_password_is_never_stored_on_flow_during_mfa(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    flows = _capture_next_flow(monkeypatch)
    install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SMS_MFA", session="SESSION-CANARY", username="alice"
            )
        ],
        mfa_results=[PlaceInvalidAuthError("invalid")],
    )
    form = await _start_user_flow(hass)
    mfa_form = await _submit_user(hass, form["flow_id"])

    assert "_password" not in vars(flows[0])
    result = await _submit_mfa(hass, mfa_form["flow_id"])
    assert result.get("step_id") == "mfa"
    assert "_password" not in vars(flows[0])
    assert PASSWORD not in repr(vars(flows[0]))
    hass.config_entries.flow.async_abort(result["flow_id"])


@pytest.mark.parametrize(
    ("stage", "error", "expected_error"),
    [
        ("authenticate", PlaceInvalidAuthError("PASSWORD-CANARY"), "invalid_auth"),
        (
            "authenticate",
            PlaceTransientAuthError("PASSWORD-CANARY"),
            "cannot_connect",
        ),
        (
            "credentials",
            PlaceInvalidAuthError("AWS-ACCESS-CANARY"),
            "invalid_auth",
        ),
        (
            "credentials",
            PlaceTransientAuthError("AWS-ACCESS-CANARY"),
            "cannot_connect",
        ),
        (
            "discovery",
            PlaceInvalidAuthError("AWS-ACCESS-CANARY"),
            "invalid_auth",
        ),
        (
            "discovery",
            PlaceDiscoveryError("AWS-ACCESS-CANARY"),
            "cannot_connect",
        ),
    ],
)
async def test_reauth_errors_return_reauth_form_without_changing_entry(  # noqa: PLR0913, PLR0917
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
    error: BaseException,
    expected_error: str,
) -> None:
    entry = _reauth_entry(hass)
    old_data = dict(entry.data)
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[error] if stage == "authenticate" else None,
        credential_results=[error] if stage == "credentials" else None,
        discover_results=[error] if stage == "discovery" else None,
    )
    form = await start_reauth_flow(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    _assert_form(result, "reauth_confirm", expected_error)
    assert entry.data == old_data
    assert harness.auth is not None
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)


async def test_base_auth_error_returns_retryable_reauth_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = _reauth_entry(hass)
    old_data = dict(entry.data)
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[PlaceAuthError("ID-TOKEN-CANARY")],
    )
    form = await start_reauth_flow(hass, entry)

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    _assert_form(result, "reauth_confirm", "cannot_connect")
    assert entry.data == old_data
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)


async def test_transient_reauth_retry_consumes_next_factory_script(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _reauth_entry(hass)
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[PlaceTransientAuthError("temporary"), None],
    )
    form = await start_reauth_flow(hass, entry)
    retry_form = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    result = await hass.config_entries.flow.async_configure(
        retry_form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    assert result.get("reason") == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "refresh-1"
    assert len(harness.auth_instances) == RETRY_ATTEMPT_COUNT


async def test_base_auth_error_after_reauth_mfa_returns_reauth_form(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entry = _reauth_entry(hass)
    old_data = dict(entry.data)
    harness = install_place_fakes(
        monkeypatch,
        authenticate_results=[
            MfaRequired(
                challenge_name="SOFTWARE_TOKEN_MFA",
                session="SESSION-CANARY",
                username="alice",
            )
        ],
        credential_results=[PlaceAuthError("AWS-ACCESS-CANARY")],
    )
    form = await start_reauth_flow(hass, entry)
    mfa_form = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONF_PASSWORD: PASSWORD}
    )

    result = await _submit_mfa(hass, mfa_form["flow_id"])

    _assert_form(result, "reauth_confirm", "cannot_connect")
    assert entry.data == old_data
    assert harness.token_cache is not None
    assert harness.token_cache.load() is None
    _assert_no_secrets(result, caplog)


async def test_reauth_without_stored_username_aborts_before_login(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _reauth_entry(
        hass,
        data={
            CONF_REFRESH_TOKEN: "refresh-old",
            CONF_ACCOUNT_ID: "identity-1",
        },
    )
    harness = install_place_fakes(monkeypatch)

    result = await start_reauth_flow(hass, entry)

    assert result.get("type") is FlowResultType.ABORT
    assert result.get("reason") == "wrong_account"
    assert harness.auth is None
    assert harness.client is None
