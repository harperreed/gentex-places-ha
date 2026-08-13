<!-- ABOUTME: Plans the SDK auth and runtime-error contract needed by Home Assistant. -->
<!-- ABOUTME: Stops before any external push, package publish, or GitHub release. -->
# PLACE SDK Authentication Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare `place-integration-api` 0.3.0 for Home Assistant by adding cache-only authentication, typed runtime auth failures, public discovery validation, and secret-safe errors.

**Architecture:** Keep Cognito and MQTT policy inside the SDK. `CognitoAuth` gets a public refresh-token-only entry point; `RealCognitoGateway` classifies proven credential rejection codes as terminal, known service/network failures as transient, and unknown service codes as generic auth errors; `PlaceConnection` reports typed SDK errors while retrying non-terminal failures and stopping on invalid credentials; `PlaceClient` exposes those errors and discovery through public callbacks and methods.

**Tech Stack:** Python 3.11+, asyncio, aiohttp, boto3/botocore, aiomqtt, pytest, pytest-asyncio, basedpyright, Ruff, uv.

## Global Constraints

- Work in a real clone of `git@github.com:harperreed/place-integration-api.git`, not `/tmp/place-integration-api.q8TCeN`.
- Create branch `wip/home-assistant-auth-contract` from current `master`; preserve unrelated changes.
- The SDK must never import Home Assistant.
- Keep `place-integration-api` version `0.3.0`; do not publish or create a GitHub release without Doctor Biz's explicit approval.
- `authenticate()` retains its interactive SRP/MFA behavior; `authenticate_from_cache()` never performs SRP.
- Only a proven Cognito credential rejection becomes `PlaceInvalidAuthError`; proven network, throttling, and service failures become `PlaceTransientAuthError`; unknown service codes remain retryable plain `PlaceAuthError` values.
- Never log or stringify usernames, passwords, MFA codes, tokens, AWS keys, MQTT topics, thing names, household IDs, device IDs, raw payloads, or full cloud responses.
- Preserve the read-only wire invariant: subscriptions and `shadow/get` publishes only.
- Follow TDD for every behavior change and keep hand-written `ABOUTME:` headers.

## Execution preflight

```bash
cd /Users/harper/Public/src/personal
test -d place-integration-api/.git || git clone git@github.com:harperreed/place-integration-api.git
cd place-integration-api
git status --short --branch
git switch -c wip/home-assistant-auth-contract
uv sync --extra dev
uv run pytest -q
uv run basedpyright
```

Expected: a clean WIP branch and the existing SDK suite and type checker pass before edits. If the clone has changed since commit `c354ea3`, re-read `src/place/auth/`, `src/place/client.py`, `src/place/transport.py`, and their tests before following line-level details below.

---

### Task 1: Typed and secret-safe Cognito failures

**State:** Complete in SDK commits `abf6d6d` and `a3c8b00`; spec and quality reviews approved.

**Files:**
- Modify: `src/place/exceptions.py`
- Modify: `src/place/__init__.py`
- Modify: `src/place/auth/cognito_gateway.py`
- Test: `tests/test_exceptions.py`
- Test: `tests/test_cognito_gateway.py`
- Test: `tests/test_public_api.py`

**Interfaces:**
- Consumes: botocore `ClientError.response["Error"]["Code"]`.
- Produces: `PlaceInvalidAuthError(PlaceAuthError)`, `PlaceTransientAuthError(PlaceAuthError)`, and sanitized gateway exceptions.

- [x] **Step 1: Add failing exception and gateway tests**

Add the public hierarchy assertion to `tests/test_exceptions.py` and public import to `tests/test_public_api.py`:

```python
from place import PlaceInvalidAuthError, PlaceTransientAuthError
from place.exceptions import PlaceAuthError


def test_invalid_auth_is_a_place_auth_error() -> None:
    assert issubclass(PlaceInvalidAuthError, PlaceAuthError)
    assert issubclass(PlaceTransientAuthError, PlaceAuthError)
```

Add these cases to `tests/test_cognito_gateway.py`, using the file's existing monkeypatch style:

```python
from botocore.exceptions import BotoCoreError, ClientError
import pytest

from place.exceptions import PlaceAuthError, PlaceInvalidAuthError, PlaceTransientAuthError


def _client_error(code: str, message: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "InitiateAuth",
    )


def test_refresh_classifies_rejected_token_without_leaking_response(monkeypatch) -> None:
    def reject(*args, **kwargs):
        raise _client_error("NotAuthorizedException", "TOKEN-CANARY")

    monkeypatch.setattr(srp_auth, "refresh_tokens", reject)
    gateway = RealCognitoGateway(PlaceConfig())

    with pytest.raises(PlaceInvalidAuthError) as caught:
        gateway.refresh("REFRESH-TOKEN-CANARY")

    assert "TOKEN-CANARY" not in str(caught.value)
    assert "REFRESH-TOKEN-CANARY" not in str(caught.value)


def test_refresh_keeps_throttling_retryable_and_secret_safe(monkeypatch) -> None:
    def throttle(*args, **kwargs):
        raise _client_error("TooManyRequestsException", "TOKEN-CANARY")

    monkeypatch.setattr(srp_auth, "refresh_tokens", throttle)
    gateway = RealCognitoGateway(PlaceConfig())

    with pytest.raises(PlaceTransientAuthError) as caught:
        gateway.refresh("REFRESH-TOKEN-CANARY")

    assert "TOKEN-CANARY" not in str(caught.value)
```

- [x] **Step 2: Run the focused tests and confirm the contract is missing**

Run:

```bash
uv run pytest tests/test_exceptions.py tests/test_cognito_gateway.py tests/test_public_api.py -q
```

Expected: FAIL because `PlaceInvalidAuthError` does not exist or is not exported.

- [x] **Step 3: Implement the typed, sanitized boundary**

Add to `src/place/exceptions.py` and export it from `src/place/__init__.py`:

```python
class PlaceInvalidAuthError(PlaceAuthError):
    """Stored or supplied credentials were rejected and require user action."""


class PlaceTransientAuthError(PlaceAuthError):
    """Authentication failed temporarily and can be retried."""
```

Replace `_as_place_auth_error` in `src/place/auth/cognito_gateway.py` with a version that never embeds the boto exception:

```python
_TRANSIENT_AUTH_CODES = frozenset(
    {"TooManyRequestsException", "InternalErrorException", "ExternalServiceException"}
)


def _as_place_auth_error(
    action: str,
    call: Callable[[], _T],
    *,
    invalid_codes: frozenset[str] = frozenset(),
) -> _T:
    """Run a Cognito call and expose a typed, secret-safe SDK error."""
    try:
        return call()
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", "UnknownClientError"))
        if code in invalid_codes:
            raise PlaceInvalidAuthError(f"{action} rejected") from None
        if code in _TRANSIENT_AUTH_CODES:
            raise PlaceTransientAuthError(f"{action} temporarily failed ({code})") from None
        raise PlaceAuthError(f"{action} failed ({code})") from None
    except BotoCoreError as exc:
        raise PlaceTransientAuthError(
            f"{action} temporarily failed ({type(exc).__name__})"
        ) from None
```

Import both new errors beside `PlaceAuthError`. Pass `frozenset({"NotAuthorizedException"})` for refresh; `frozenset({"NotAuthorizedException", "UserNotFoundException", "PasswordResetRequiredException", "UserNotConfirmedException"})` for SRP; and `frozenset({"CodeMismatchException", "ExpiredCodeException", "NotAuthorizedException", "UserNotFoundException"})` for MFA. Pass no invalid codes for the IoT identity exchange because `NotAuthorizedException` there has other authorization causes. Tests cover every set and an unknown code.

- [x] **Step 4: Run focused and full SDK checks**

Run:

```bash
uv run pytest tests/test_exceptions.py tests/test_cognito_gateway.py tests/test_public_api.py -q
uv run pytest -q
uv run basedpyright
```

Expected: all commands PASS with no new warnings.

- [x] **Step 5: Commit**

```bash
git status --short
git add src/place/exceptions.py src/place/__init__.py src/place/auth/cognito_gateway.py tests/test_exceptions.py tests/test_cognito_gateway.py tests/test_public_api.py
git commit -m "feat(auth): classify rejected credentials"
```

---

### Task 2: Cache-only runtime authentication

**State:** Complete in SDK commits `25e625f`, `7732e81`, `4dcdcae`, and `c3a6830`; spec and quality reviews approved.

**Files:**
- Modify: `src/place/auth/cognito_auth.py`
- Test: `tests/test_cognito_auth.py`

**Interfaces:**
- Consumes: `TokenCache.load() -> dict[str, Any] | None`, `CognitoGateway.refresh(refresh_token)`.
- Produces: `async CognitoAuth.authenticate_from_cache(username: str) -> None`.

- [x] **Step 1: Write cache-only authentication tests**

Add to `tests/test_cognito_auth.py`:

```python
from place.exceptions import PlaceInvalidAuthError


async def test_authenticate_from_cache_uses_refresh_and_never_srp() -> None:
    gw = FakeGateway(
        refresh={"AccessToken": "access-cached", "IdToken": "id-cached", "ExpiresIn": 3600}
    )
    cache = FakeCache({"username": "alice", "refresh_token": "rt-cached"})
    auth = CognitoAuth(PlaceConfig(), websession=object(), gateway=gw, token_cache=cache)  # pyright: ignore[reportArgumentType]

    await auth.authenticate_from_cache("alice")

    assert await auth.async_get_access_token() == "access-cached"
    assert gw.refresh_calls == 1
    assert gw.login_calls == 0
    assert auth._refresh_token == "rt-cached"


@pytest.mark.parametrize(
    "cached",
    [None, {}, {"username": "bob", "refresh_token": "rt"}, {"username": "alice"}],
)
async def test_authenticate_from_cache_rejects_missing_matching_token(cached) -> None:
    gw = FakeGateway()
    auth = CognitoAuth(
        PlaceConfig(),
        websession=object(),  # pyright: ignore[reportArgumentType]
        gateway=gw,
        token_cache=FakeCache(cached),
    )

    with pytest.raises(PlaceInvalidAuthError):
        await auth.authenticate_from_cache("alice")

    assert gw.login_calls == 0
    assert gw.refresh_calls == 0


async def test_authenticate_from_cache_propagates_rejected_refresh_without_srp() -> None:
    gw = FakeGateway(refresh_error=PlaceInvalidAuthError("token refresh rejected"))
    auth = CognitoAuth(
        PlaceConfig(),
        websession=object(),  # pyright: ignore[reportArgumentType]
        gateway=gw,
        token_cache=FakeCache({"username": "alice", "refresh_token": "rt-stale"}),
    )

    with pytest.raises(PlaceInvalidAuthError):
        await auth.authenticate_from_cache("alice")

    assert gw.login_calls == 0
```

- [x] **Step 2: Run tests and confirm failure**

Run: `uv run pytest tests/test_cognito_auth.py -q`

Expected: FAIL with `CognitoAuth` missing `authenticate_from_cache`.

- [x] **Step 3: Implement the public cache-only method**

Add this method to `CognitoAuth` and import both typed auth errors:

```python
async def authenticate_from_cache(self, username: str) -> None:
    """Authenticate only with this username's cached refresh token."""
    self._username = username
    if self._token_cache is None:
        raise PlaceInvalidAuthError("no refresh-token cache configured")
    try:
        cached = self._token_cache.load()
    except Exception:
        logger.warning("token cache load failed")
        raise PlaceTransientAuthError("refresh-token cache unavailable") from None
    if not cached or cached.get("username") != username:
        raise PlaceInvalidAuthError("no refresh token for username")
    refresh_token = cached.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise PlaceInvalidAuthError("no refresh token for username")
    auth = await asyncio.to_thread(self._gateway.refresh, refresh_token)
    auth.setdefault("RefreshToken", refresh_token)
    self._store_tokens(auth)
```

Do not implement this by calling `authenticate(username, "")`; that method deliberately falls back to SRP.

Also change interactive `authenticate()` so a confirmed invalid cached token falls back to the supplied password, while `PlaceTransientAuthError` propagates instead of hiding an outage behind a second login attempt. Add tests for both branches and convert the existing rejected-cache test to raise `PlaceInvalidAuthError`.

- [x] **Step 4: Verify**

Run:

```bash
uv run pytest tests/test_cognito_auth.py -q
uv run pytest -q
uv run basedpyright
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/place/auth/cognito_auth.py tests/test_cognito_auth.py
git commit -m "feat(auth): add cache-only login"
```

---

### Task 3: Public discovery validation

**State:** Complete in SDK commits `ad5d38d` and `2785812`; spec and quality reviews approved.

**Files:**
- Modify: `src/place/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `Discoverer.discover() -> list[DiscoverDevice]`.
- Produces: `async PlaceClient.async_discover() -> list[DiscoverDevice]`; `start()` reuses it.

- [x] **Step 1: Write the failing public-discovery test**

Add to `tests/test_client.py`, using its existing client/fake constructors:

```python
async def test_async_discover_returns_provider_devices_without_starting_connection() -> None:
    discovered = [_discovered("thing-a")]
    provider = FakeProvider(discovered)
    connection = FakeConnection()
    client = _client(provider=provider, connection=connection)

    result = await client.async_discover()

    assert result == discovered
    assert provider.calls == 1
    assert connection.run_calls == 0
```

If the existing fakes use different counter names, add those counters rather than introducing mocks.

- [x] **Step 2: Run and see the missing method**

Run: `uv run pytest tests/test_client.py -q`

Expected: FAIL with `PlaceClient` missing `async_discover`.

- [x] **Step 3: Add the method and make startup use it**

```python
async def async_discover(self) -> list[DiscoverDevice]:
    """Return devices visible to the authenticated account without starting MQTT."""
    return await self._provider.discover()
```

Change the first line of `start()` from `self._provider.discover()` to `self.async_discover()`. Do not duplicate discovery parsing in the Home Assistant integration.

- [x] **Step 4: Verify and commit**

Run:

```bash
uv run pytest tests/test_client.py tests/test_provider.py -q
uv run pytest -q
uv run basedpyright
```

Expected: PASS.

```bash
git add src/place/client.py tests/test_client.py
git commit -m "feat: expose account discovery"
```

---

### Task 4: Runtime error notifications and terminal invalid auth

**Files:**
- Modify: `src/place/client.py`
- Modify: `src/place/transport.py`
- Test: `tests/test_client.py`
- Test: `tests/test_place_connection.py`

**Interfaces:**
- Consumes: `PlaceError`, `PlaceInvalidAuthError`.
- Produces: `PlaceClient.on_error(callback: Callable[[PlaceError], None]) -> Callable[[], None]`; connection factories accept `(on_message, on_state, on_error)`; invalid auth stops reconnect, while other SDK errors notify and retry.

- [ ] **Step 1: Test connection error policy**

Add focused scenarios to `tests/test_place_connection.py` with its hand-written transports/auth fakes:

```python
async def test_invalid_auth_notifies_once_and_stops_reconnect() -> None:
    error = PlaceInvalidAuthError("token refresh rejected")
    auth = ScriptedAuth(errors=[error])
    seen: list[PlaceError] = []
    sleeps: list[float] = []
    conn = PlaceConnection(
        PlaceConfig(),
        auth,
        transport_factory=unused_transport_factory,
        on_message=lambda topic, payload: None,
        on_error=seen.append,
        sleep=_recording_sleep(sleeps),
    )

    await conn.run()

    assert seen == [error]
    assert sleeps == []
    assert auth.calls == 1


async def test_transient_auth_notifies_and_retries() -> None:
    transient = PlaceAuthError("temporary credential exchange failure")
    auth = ScriptedAuth(errors=[transient], then_credentials=_credentials())
    seen: list[PlaceError] = []
    conn = _connection(auth=auth, on_error=seen.append, stop_after_connect=True)

    await conn.run()

    assert seen == [transient]
    assert auth.calls == 2


async def test_mqtt_failure_notifies_with_sanitized_connection_error() -> None:
    seen: list[PlaceError] = []
    conn = _connection(
        transport_error=MqttError("BROKER-SECRET-CANARY"),
        on_error=seen.append,
        stop_after_error=True,
    )

    await conn.run()

    assert len(seen) == 1
    assert isinstance(seen[0], PlaceConnectionError)
    assert "BROKER-SECRET-CANARY" not in str(seen[0])
```

Adapt constructor helpers to the current test file, but assert these exact outcomes.

- [ ] **Step 2: Test client listener registration and unsubscribe**

Update `FakeConnection`/`connection_factory` in `tests/test_client.py` to accept an error callback, then add:

```python
def test_on_error_forwards_typed_error_and_unsubscribes() -> None:
    client, connection = _client_and_connection()
    seen: list[PlaceError] = []
    unsubscribe = client.on_error(seen.append)
    first = PlaceAuthError("temporary")
    connection.emit_error(first)
    unsubscribe()
    connection.emit_error(PlaceInvalidAuthError("rejected"))

    assert seen == [first]
```

- [ ] **Step 3: Run and confirm failures**

Run:

```bash
uv run pytest tests/test_place_connection.py tests/test_client.py -q
```

Expected: FAIL because connection/client error callbacks do not exist and invalid auth still enters backoff.

- [ ] **Step 4: Implement connection error policy**

In `src/place/transport.py`, add `on_error` to `PlaceConnection.__init__` and store it. Split the catch tail exactly by terminal versus retryable SDK failure:

```python
except PlaceInvalidAuthError as exc:
    if self._on_error is not None:
        self._on_error(exc)
    break
except PlaceError as exc:
    if self._on_error is not None:
        self._on_error(exc)
    if self._stopped:
        break
    await self._backoff(attempt, exc)
    attempt += 1
except MqttError as exc:
    if self._on_error is not None:
        self._on_error(PlaceConnectionError("MQTT connection failed"))
    if self._stopped:
        break
    await self._backoff(attempt, exc)
    attempt += 1
```

Extract only the existing delay/log/sleep block into `_backoff`; do not change its formula. Log `type(exc).__name__`, not `str(exc)`, so future exception text cannot leak.

- [ ] **Step 5: Implement client fan-out**

In `src/place/client.py`:

```python
OnError = Callable[[PlaceError], None]
ConnectionFactory = Callable[[OnMessage, OnState, OnError], Connection]
```

Add `_error_listeners`, pass `_emit_error` through `create()` and the constructor factory call, and expose:

```python
def on_error(self, callback: OnError) -> Callable[[], None]:
    """Register for typed connection/auth errors."""
    return self._register(self._error_listeners, callback)

def _emit_error(self, error: PlaceError) -> None:
    for callback in list(self._error_listeners):
        callback(error)
```

Update every test connection factory to the three-callback signature. Do not keep a two-argument compatibility path; 0.3.0 is not yet public and Doctor Biz has not approved a shim.

- [ ] **Step 6: Verify and commit**

Run:

```bash
uv run pytest tests/test_place_connection.py tests/test_client.py -q
uv run pytest -q
uv run basedpyright
```

Expected: PASS with invalid auth causing no sleep/retry and transient auth causing one notification plus retry.

```bash
git status --short
git add src/place/client.py src/place/transport.py tests/test_client.py tests/test_place_connection.py
git commit -m "feat: report runtime authentication failures"
```

---

### Task 5: Canonical checks, documentation, and 0.3.0 release candidate

**Files:**
- Create: `scripts/check`
- Create: `scripts/check_release.py`
- Create: `tests/test_release.py`
- Modify: `.github/workflows/pypi.yml`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `examples/quickstart.py`
- Test: `tests/test_public_api.py`

**Interfaces:**
- Consumes: Tasks 1–4 public APIs.
- Produces: one canonical verification command and release documentation; no external release.

- [ ] **Step 1: Lock the public contract in the API test**

Extend `tests/test_public_api.py`:

```python
def test_home_assistant_auth_contract_is_public() -> None:
    from place import (
        CognitoAuth,
        PlaceAuthError,
        PlaceClient,
        PlaceInvalidAuthError,
        PlaceTransientAuthError,
    )

    assert hasattr(CognitoAuth, "authenticate_from_cache")
    assert hasattr(PlaceClient, "async_discover")
    assert hasattr(PlaceClient, "on_error")
    assert issubclass(PlaceInvalidAuthError, PlaceAuthError)
    assert issubclass(PlaceTransientAuthError, PlaceAuthError)
```

- [ ] **Step 2: Add Ruff and the canonical check script**

Add `ruff`, `build`, and `twine` to `[project.optional-dependencies].dev`, then create executable `scripts/check`:

```sh
#!/bin/sh
# ABOUTME: Runs every SDK quality gate used locally and in CI.
# ABOUTME: Stops on the first formatting, lint, type, or test failure.
set -eu

uv sync --extra dev
uv run ruff format --check src tests examples
uv run ruff check src tests examples
uv run basedpyright
uv run pytest
sdk_dist_dir=$(mktemp -d)
trap 'rm -rf "$sdk_dist_dir"' EXIT HUP INT TERM
uv build --out-dir "$sdk_dist_dir"
uv run twine check "$sdk_dist_dir"/*
```

Run `chmod +x scripts/check` and `uv lock` so dependency resolution is reproducible. The temporary directory is explicit and narrow; the trap never targets the repo.

- [ ] **Step 3: Document the supported flows and read-only boundary**

Replace the one-line README with concise sections that contain these verified examples:

```python
# Interactive setup: SRP, then MFA if requested.
await auth.authenticate(username, password)

# Stored-session startup: refresh token only, never SRP fallback.
await auth.authenticate_from_cache(username)

client = PlaceClient.create(PlaceConfig(), auth)
devices = await client.async_discover()
unsubscribe = client.on_error(handle_place_error)
```

Document that `PlaceInvalidAuthError` needs user action, other `PlaceAuthError` values may be transient, and the client remains read-only. Update `examples/quickstart.py` only if its existing constructor differs from the final public signature.

- [ ] **Step 4: Run the full release-candidate checks and inspect the wheel**

Before the full checks, create `scripts/check_release.py` with `argparse` and `tomllib`. Its public helper `version_for_tag(tag: str, pyproject: Path) -> str` strips one leading `v`, compares it with `[project].version`, and raises `ValueError("tag <tag> does not match project version <version>")` on mismatch. Test `v0.3.0` and `0.3.0` success plus `v0.3.1` failure in `tests/test_release.py`.

Change `.github/workflows/pypi.yml` to run in this order: checkout full tag history; verify `${GITHUB_REF_NAME}` with `scripts/check_release.py`; run `scripts/check`; build once; publish the checked artifact to PyPI through the existing trusted-publishing environment; create the GitHub release only after PyPI publish succeeds. Keep least-privilege permissions, granting `id-token: write` only to the publish job and `contents: write` only to the final release job.

Run:

```bash
scripts/check
uv build
unzip -l dist/place_integration_api-0.3.0-py3-none-any.whl
uv run python scripts/check_release.py --tag v0.3.0
uv run python -c 'from place import CognitoAuth, PlaceClient, PlaceInvalidAuthError, PlaceTransientAuthError, __version__; assert __version__ == "0.3.0"; assert hasattr(CognitoAuth, "authenticate_from_cache"); assert hasattr(PlaceClient, "on_error")'
git diff --check
```

Expected: checks PASS; the wheel contains `place/py.typed`; import assertion exits zero. Delete neither build artifacts nor user data automatically; keep `dist/` ignored by Git.

- [ ] **Step 5: Fresh-eyes review and commit**

Run the fresh-eyes review over all branch changes, fix findings with focused tests, rerun `scripts/check`, then:

```bash
git status --short
git add pyproject.toml uv.lock scripts/check scripts/check_release.py tests/test_release.py .github/workflows/pypi.yml README.md examples/quickstart.py tests/test_public_api.py
git commit -m "ci: validate SDK releases before publishing"
```

- [ ] **Step 6: Stop at the external release gate**

Record the candidate commit and the output of `scripts/check`. Do not run `git push`, create a GitHub release, or publish to PyPI in this plan. Doctor Biz must authorize those external writes after reviewing the SDK branch. The Home Assistant plan does not begin until PyPI serves this exact SDK contract; this keeps its lock file and clean-install tests honest.
