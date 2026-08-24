# Multi-Device Login Implementation Plan

## Objective

Replace the current shared `User.api_secret` login behavior with independently revocable credentials for each client installation.

The administrator will configure only the maximum number of devices that may be logged in for one user. A limit of `1` provides single-device login. Higher values permit multiple devices without invalidating credentials that are still within the configured limit.

When a new device exceeds the limit, the oldest active device credential will be revoked and the new device will be admitted.

## Current Behavior and Root Cause

Token-producing login flows currently call `issue_user_api_credentials()` in `flutter_utils/api/auth.py`.

That function:

1. Uses the single `api_key` stored on the Frappe `User`.
2. Generates a new `api_secret` during every login.
3. Overwrites the encrypted `User.api_secret`.

Frappe accepts only the latest secret associated with that user. Consequently, logging in again immediately invalidates the token stored on every previously logged-in device.

A numeric device limit cannot be implemented correctly with one shared user secret. Each device needs a separately stored credential that can be revoked without affecting the other devices.

## Confirmed Product Decisions

- Use one numeric setting rather than an enable checkbox.
- Setting name: `Maximum Logged-in Devices`.
- Default value: `1`.
- Minimum value: `1`.
- A new login over the limit expires the oldest active device credential.
- Reducing the configured limit prunes excess credentials immediately through an after-commit background job.
- This implementation includes the backend contract and migrations for `flutter_apps/xealth_admin` and `flutter_apps/xealth_employee`.
- Other Flutter and Next.js consumers remain separate work.
- Device limits apply to API-token login flows, not ordinary Frappe Desk/browser sessions.

## Scope

### Included

- Password login through `flutter_utils.api.auth.login`.
- OTP login through `verify_otp` and its compatibility wrappers.
- OTP signup credentials returned by `verify_otp` and its compatibility wrappers.
- Firebase native-token login through `firebase_token_login`.
- Per-device API credential storage and authentication.
- Automatic revocation of the oldest active credential.
- Server-side logout for the calling device.
- Background pruning when the administrator lowers the limit.
- API contract and migration documentation.
- Automated backend tests.
- `flutter_apps/xealth_admin` device identity, login, request authentication, realtime, assistant iframe, logout, and test migration.
- `flutter_apps/xealth_employee` device identity, OTP login, request authentication, logout, and test migration.

### Excluded

- `firebase_session_login`, because it creates a browser-compatible Frappe session rather than API credentials.
- Standard Frappe Desk login/session limits.
- Flutter clients other than `xealth_admin` and `xealth_employee`.
- Next.js client changes.
- A device-management frontend for listing or manually revoking devices.
- Push-notification token management.
- Device fingerprinting based on hardware identifiers.

## Settings Changes

Add the following field to the `Flutter Utils Settings` DocType:

| Property | Value |
|---|---|
| Label | Maximum Logged-in Devices |
| Fieldname | `maximum_logged_in_devices` |
| Fieldtype | Int |
| Default | `1` |
| Required | Yes |
| Description | Maximum number of active API-token device logins allowed per user. A new login revokes the oldest active device when this limit is reached. |

Place the field in a new `Device Login Settings` section so it is not coupled visually to OTP or Firebase configuration.

### Validation

`FlutterUtilsSettings.validate()` must reject missing, zero, or negative values:

```text
Maximum Logged-in Devices must be at least 1.
```

The Python type annotation generated for the settings controller must include:

```python
maximum_logged_in_devices: DF.Int
```

## Device Credential DocType

Create a new DocType named `Flutter Device Credential` in the `Flutter Utils` module.

Frappe already supports authenticating API credentials from a DocType selected through the `Frappe-Authorization-Source` request header. The new DocType will conform to that native contract instead of patching Frappe authentication internals.

### Fields

| Label | Fieldname | Type | Requirements |
|---|---|---|---|
| User | `user` | Link / User | Required and indexed |
| Device ID Hash | `device_id_hash` | Data | Required and indexed; never store the raw installation ID |
| Device Name | `device_name` | Data | Optional, sanitized display metadata |
| API Key | `api_key` | Data | Required, unique, indexed |
| API Secret | `api_secret` | Password | Required and encrypted through Frappe password storage |
| Enabled | `enabled` | Check | Required; default `1` |
| Last Login At | `last_login_at` | Datetime | Required for active credentials |
| Revoked At | `revoked_at` | Datetime | Set when disabled |
| Revocation Reason | `revocation_reason` | Select | Empty, `Device Logout`, `Device Limit`, `Limit Reduced`, `Credential Rotated` |

The standard document creation and modification timestamps provide the audit timestamps in addition to the explicit login and revocation timestamps.

### Naming and Uniqueness

- Use a generated document name; do not expose the device identifier through the document name.
- `api_key` must be globally unique because Frappe resolves the authentication source by API key.
- The active credential lookup key is `(user, device_id_hash)`.
- Application logic must prevent multiple active records for the same user and device hash.

### Permissions

- System Managers may read and delete credential records for support and recovery.
- Ordinary users must not receive Desk read access to other users' device records.
- Password fields remain masked and are never returned by list/detail APIs.
- Login and logout code performs controlled writes with explicit permission bypass where required.

## Device Identity Contract

Every API-token login request must include a stable client-installation identifier:

| Parameter | Required | Description |
|---|---|---|
| `device_id` | Yes | Random UUID generated once by the client and persisted for that app installation |
| `device_name` | No | Human-readable value such as `iPhone 17 Pro` or `Chrome on macOS` |

The client must generate a random installation UUID. It must not send IMEI, serial number, MAC address, advertising ID, or another hardware identifier.

The backend will normalize and validate `device_id`, then store only:

```text
SHA-256(normalized device_id)
```

Recommended validation:

- Trim surrounding whitespace.
- Require a non-empty value.
- Set a reasonable maximum request length before hashing, for example 128 characters.
- Prefer UUID-formatted identifiers, while allowing an explicitly documented opaque installation ID if existing clients need it.
- Trim `device_name` and cap it at a safe display length, for example 140 characters.

The device ID associates repeated authenticated logins with one installation. It is not treated as an authentication secret.

## Login API Changes

### Password Login

Current endpoint:

```python
login(usr: str, pwd: str) -> dict
```

New contract:

```python
login(
	usr: str,
	pwd: str,
	device_id: str,
	device_name: str | None = None,
) -> dict
```

Password authentication remains unchanged. After successful Frappe authentication, issue a device credential instead of rotating `User.api_secret`.

### Generic OTP Verification

Add `device_id` and `device_name` to `verify_otp()` for the `login` and `signup` purposes.

They are not needed for `reset_password`, because that flow does not issue credentials. Validate their presence only when the selected purpose produces an authenticated token.

### OTP Compatibility Wrappers

Pass device information through all wrappers that issue credentials:

- `verify_login_otp`
- `verify_mobile_login_otp`
- `verify_signup_otp`
- `verify_mobile_signup_otp`

OTP send endpoints do not need device fields because they do not issue credentials.

### Firebase Token Login

Current endpoint:

```python
firebase_token_login(id_token: str) -> dict
```

New contract:

```python
firebase_token_login(
	id_token: str,
	device_id: str,
	device_name: str | None = None,
) -> dict
```

Firebase verification and user resolution remain unchanged. Credential issuance moves to the per-device credential service.

### Signup

New users must no longer be created with a shared `User.api_secret` intended for the mobile client.

The signup flow should:

1. Create the Frappe user.
2. Persist the user transaction successfully.
3. Issue the first `Flutter Device Credential` for the supplied installation ID.
4. Return the same normalized authentication response used by all other token login paths.

## Authentication Response

Keep existing fields and add the authorization source:

```json
{
  "api_key": "generated-device-api-key",
  "api_secret": "generated-device-api-secret",
  "authorization_source": "Flutter Device Credential",
  "full_name": "Example User",
  "email": "user@example.com",
  "mobile_no": "+919000000000"
}
```

`authorization_source` is additive, but using the returned credentials without the corresponding header will fail because the API key belongs to `Flutter Device Credential`, not `User`.

Do not return the device hash, credential document name, revocation metadata, or configured device limit unless a concrete client requirement is added later.

## Authenticated Request Contract

Clients must send both headers on every authenticated request:

```http
Authorization: token <api_key>:<api_secret>
Frappe-Authorization-Source: Flutter Device Credential
```

Frappe will then:

1. Find an enabled `Flutter Device Credential` by `api_key`.
2. Compare the supplied secret with its encrypted `api_secret`.
3. Resolve the authenticated user from the credential's `user` field.
4. Reject disabled, missing, or incorrectly signed credentials.

This uses Frappe's existing `validate_auth_via_api_keys()` and `validate_api_key_secret()` behavior and avoids a global monkey patch.

## Credential Issuance Service

Replace `issue_user_api_credentials()` with a focused device-aware service, for example:

```python
issue_device_api_credentials(
	user: User,
	device_id: str,
	device_name: str | None = None,
) -> dict
```

The exact function name may follow existing module conventions, but all token-producing endpoints must use one shared implementation.

### Transaction and Concurrency

Credential-limit enforcement must be atomic. Two simultaneous logins must not both observe a free slot and create credentials over the configured limit.

Within the request transaction:

1. Lock the user's row with `frappe.db.get_value(..., for_update=True)`.
2. Read the current setting.
3. Find the credential matching `(user, device_id_hash)`.
4. Count enabled credentials for the user.
5. Revoke excess/oldest credentials when required.
6. Create or rotate the current device credential.
7. Return the generated secret once.

Do not add an explicit commit inside the ordinary login request. Let Frappe commit or roll back the request transaction as one unit.

### Existing Device Login

When an enabled credential already exists for the same user and device hash:

1. Do not consume a second device slot.
2. Generate a new API secret for that credential.
3. Update the optional device name.
4. Update `last_login_at`.
5. Ensure `enabled = 1` and clear stale revocation metadata.
6. Return the existing API key and new secret.

Rotating that device's secret invalidates an older copied token for the same installation without affecting other devices.

### Returning Revoked Device Login

When a disabled credential exists for the same device hash:

1. Treat it as a new admission into the active-device set.
2. Apply the current limit and revoke the oldest active credential if necessary.
3. Rotate its API secret.
4. Re-enable it and clear revocation metadata.
5. Update `last_login_at` and device name.

Reusing the record preserves audit continuity and avoids unlimited duplicate records for repeated reinstalls using the same persisted ID.

### New Device Below the Limit

Create a new credential with:

- A cryptographically random API key.
- A cryptographically random API secret.
- The authenticated user.
- The device hash and optional display name.
- `enabled = 1`.
- `last_login_at = now()`.

Store the secret with Frappe's encrypted password helper and return the plaintext value only in the successful login response.

### New Device at the Limit

When the number of enabled credentials is already equal to or greater than the configured limit:

1. Sort active credentials by `last_login_at` ascending, then by creation ascending as a deterministic tie-breaker.
2. Revoke enough oldest credentials to create one slot for the current login.
3. Set `enabled = 0`.
4. Set `revoked_at = now()`.
5. Set `revocation_reason = "Device Limit"`.
6. Issue or reactivate the current device credential.

This makes the new login successful while old devices receive an authentication failure on their next request.

`last_login_at` means the most recent successful authentication on that installation. It is intentionally not updated on every API request, avoiding a database write for every authenticated request.

## Device Logout Endpoint

Add an authenticated POST endpoint, for example:

```python
@frappe.whitelist(methods=["POST"])
def logout_device() -> dict:
	...
```

The endpoint must identify the calling credential from the authorization headers rather than trusting a client-supplied user or credential document name.

Validation:

- Require `Frappe-Authorization-Source: Flutter Device Credential`.
- Parse and validate the current API key from the token header.
- Confirm that the credential belongs to `frappe.session.user`.

On success:

- Set `enabled = 0`.
- Set `revoked_at = now()`.
- Set `revocation_reason = "Device Logout"`.
- Return a stable success response.

Example:

```json
{
  "message": "Device logged out successfully."
}
```

The client should call this endpoint before deleting its locally stored credentials. If the request cannot reach the server, a future login can still reclaim a slot by revoking the oldest credential.

## Reducing the Configured Limit

Lowering `maximum_logged_in_devices` must prune existing credentials without blocking the settings save request.

### Settings Hook

During settings update:

1. Compare the saved value with `get_doc_before_save()`.
2. If the value was reduced, enqueue a pruning job with `enqueue_after_commit=True`.
3. Pass only the new numeric limit to the job.

Do not enqueue pruning when the limit is unchanged or increased.

### Background Job

The job should process users with active device credentials in bounded batches.

For each affected user:

1. Lock the user or otherwise serialize pruning against credential issuance.
2. Read enabled credentials ordered by `last_login_at` descending and creation descending.
3. Keep the newest credentials up to the new limit.
4. Disable all older excess credentials.
5. Set `revoked_at` and `revocation_reason = "Limit Reduced"`.
6. Commit at intentional batch boundaries so a large installation does not hold one unbounded transaction.

The job must be idempotent. Re-running it at the same limit must not revoke additional permitted credentials.

Failures should be logged without exposing API keys or secrets. A failed batch can be retried safely.

## Legacy User Credentials

Existing clients currently hold credentials stored on `User.api_key` and `User.api_secret`. Those credentials are not subject to the new device table and would bypass the numeric limit if left active.

On the first successful managed-device login for a user:

1. Detect that the user has no existing `Flutter Device Credential` records.
2. Invalidate the legacy `User.api_secret` by replacing it with an unreturned random secret, or clear the legacy API credential using a verified Frappe-safe approach.
3. Issue the first managed device credential.

This transition intentionally logs out clients still using the legacy shared credential.

Important: a Frappe user API key may also be used by integrations unrelated to Flutter Utils. Deployment owners must review such integrations before enabling the new contract. The current Flutter Utils login flow already rotates `User.api_secret` on each login, so these user credentials are not currently safe as stable integration credentials; integrations should use dedicated integration users or OAuth credentials.

New signup flows must not create or expose a shared `User.api_secret`.

## Error Contract

Use stable, translatable errors without exposing credential details.

Recommended messages and error codes:

| Condition | Message | Suggested code |
|---|---|---|
| Missing device ID | Device ID is required for token login. | `device_id_required` |
| Invalid device ID | Device ID is invalid. | `device_id_invalid` |
| Invalid limit | Maximum Logged-in Devices must be at least 1. | `invalid_device_limit` |
| Unsupported logout source | This credential is not a managed device login. | `invalid_device_credential` |
| Revoked credential request | Use Frappe's standard authentication failure response. | Existing auth error |

Do not reveal which device was evicted in a public login response unless a future product requirement calls for that information.

## Security Requirements

- Generate API keys and secrets with cryptographically secure Frappe helpers.
- Never log plaintext API secrets, authorization headers, Firebase tokens, OTPs, or raw device IDs.
- Store API secrets only through Frappe's encrypted password mechanism.
- Return a plaintext secret only at issuance/rotation time.
- Hash device IDs before persistence.
- Do not trust a client-supplied user when issuing, listing, or revoking credentials.
- Verify the resolved user remains enabled before credential issuance.
- Enforce the limit inside a transaction protected against concurrent logins.
- Use constant behavior and generic messages for invalid credentials.
- Keep credential authentication on Frappe's native authorization-source path.
- Do not perform a database write on every authenticated API request.

## Proposed File Changes

Expected backend changes:

```text
flutter_utils/
  api/auth.py
  hooks.py                         # only if a document event or scheduler hook is needed
  tests/test_auth.py
  tests/test_device_credentials.py
  flutter_utils/doctype/
    flutter_utils_settings/
      flutter_utils_settings.json
      flutter_utils_settings.py
    flutter_device_credential/
      __init__.py
      flutter_device_credential.json
      flutter_device_credential.py
  device_credentials.py            # shared issuance, revocation, and pruning service
README.md
```

Keep endpoint orchestration in `api/auth.py` and place reusable credential lifecycle logic in one backend module. Avoid duplicating limit enforcement across password, OTP, signup, and Firebase flows.

The exact service filename can change if an existing project convention provides a better location.

Expected `xealth_admin` client changes:

```text
flutter_apps/xealth_admin/
  pubspec.yaml
  lib/core/api/api_client.dart
  lib/core/realtime/frappe_realtime_service.dart
  lib/core/services/device_identity_service.dart
  lib/core/utils/shared_prefs_helper.dart
  lib/features/auth/data/auth_repository.dart
  lib/features/assistant/screens/assistant_screen_web.dart
  test/core/services/device_identity_service_test.dart
  test/core/utils/shared_prefs_helper_test.dart
  test/features/auth/data/auth_repository_test.dart
```

Expected `xealth_employee` client changes:

```text
flutter_apps/xealth_employee/
  pubspec.yaml
  lib/core/api/api_client.dart
  lib/core/services/device_identity_service.dart
  lib/core/utils/shared_prefs_helper.dart
  lib/features/auth/data/auth_repository.dart
  test/core/api/api_client_test.dart
  test/core/services/device_identity_service_test.dart
  test/core/utils/shared_prefs_helper_test.dart
  test/features/auth/data/auth_repository_test.dart
```

Only add files that are needed by the final implementation. Follow each app's existing test organization if it differs from the proposed paths.

## Flutter Client Migration

Both selected apps currently persist only `api_key` and `api_secret`, send only the `Authorization` header, and clear credentials locally on logout. They must migrate as one coordinated contract change with the backend.

### Shared Client Rules

Apply the following behavior to both apps:

1. Generate one random UUID v4 for the app installation.
2. Persist it through the app's `SharedPrefsHelper` under a dedicated key such as `flutter_utils_device_id`.
3. Reuse the same ID across logout, login, app restarts, and user changes on that installation.
4. Do not remove the device ID in `clearSession()`.
5. A reinstall, browser storage reset, or app-data reset may create a new device ID and therefore count as a new device.
6. Never derive the ID from IMEI, serial number, MAC address, advertising ID, Firebase token, username, or another hardware/account identifier.
7. Obtain an optional human-readable device name without treating it as unique or trusted.
8. Send `device_id` and `device_name` only to token-producing login/verification endpoints. OTP send requests remain unchanged.
9. Validate that the login response contains the expected `authorization_source` value.
10. Send `Frappe-Authorization-Source: Flutter Device Credential` with every request carrying the returned token pair.
11. Call the authenticated `logout_device` endpoint before clearing local credentials.
12. Always clear local credentials in a `finally` block so logout still completes locally when the server is unreachable.
13. Keep the installation device ID when a `401` response clears an expired/revoked session.

Persist the authorization source with each newly issued session so legacy User credentials are not mislabeled as managed device credentials. Validate it against a shared contract constant rather than repeating unchecked string literals throughout repositories and interceptors.

Suggested constant:

```dart
const flutterDeviceCredentialSource = 'Flutter Device Credential';
```

### Dependencies and Device Metadata

Add the `uuid` package to both apps for UUID v4 generation. Add `device_info_plus` only if the implementation supplies a useful device name; because `device_name` is optional, do not block login when metadata lookup fails.

The identity service should:

- Return an existing non-empty persisted ID when present.
- Generate, persist, and return a UUID v4 when absent.
- Serialize concurrent first calls so two login actions cannot generate different IDs.
- Return a short, bounded display name when available.
- Fall back to a generic platform label or `null` when device metadata is unavailable.
- Never log the generated ID or device metadata as authentication data.

Suggested names include `Chrome on macOS`, `Windows Desktop`, `iPhone`, or an Android model. Avoid sending the full browser user-agent string because it is long and unnecessarily identifying.

### Existing Sessions During Upgrade

Credentials already stored by released app versions belong to the Frappe `User` DocType and have no authorization source. Do not silently label those credentials as `Flutter Device Credential`; they will not exist in that DocType and authentication will fail.

On application upgrade:

- Existing credentials may continue through the old path only until the backend invalidates the legacy `User.api_secret`.
- A `401` clears the old local session and routes the user to login through the existing app behavior.
- The next successful login receives managed device credentials and uses the new source header.
- If proactive migration is preferred, clear legacy credentials once based on a local auth-contract version key and require login immediately after upgrade.

The implementation must choose and test one rollout strategy. The lowest-risk coordinated release is to deploy client support first in a backward-compatible form, then enable backend issuance and legacy invalidation. If the backend requires `device_id` immediately, both app releases must be available before production backend deployment.

## Xealth Admin Migration

`xealth_admin` uses username/password token login, supports Flutter web/desktop/mobile targets, has a shared Dio interceptor, connects to Frappe Socket.IO, and forwards credentials to an assistant iframe.

### Device Identity

Add `lib/core/services/device_identity_service.dart`.

The service should use `SharedPrefsHelper` for persistence rather than accessing `SharedPreferences` directly outside the helper. On Flutter web, `SharedPreferences` maps to browser-origin storage, so tabs in the same browser profile share one installation ID while a different profile or browser receives another ID.

Extend `lib/core/utils/shared_prefs_helper.dart` with focused methods such as:

```dart
static Future<String?> deviceId();
static Future<void> saveDeviceId(String deviceId);
```

Do not add `_deviceIdKey` to `clearSession()`. Existing non-authentication preferences must continue to survive logout.

### Password Login

Update `lib/features/auth/data/auth_repository.dart`:

1. Resolve `deviceId` and optional `deviceName` before the login request.
2. Add `device_id` and `device_name` to the JSON sent to `flutter_utils.api.auth.login`.
3. Parse `authorization_source` from the response.
4. Reject a missing or unexpected source as an invalid authentication response.
5. Save the returned API key, secret, and validated authorization source.
6. Continue loading Frappe defaults and checking `canAccessXealthAdmin` after login.
7. If access is denied after credentials were issued, call `logout_device` best-effort before clearing local state so the rejected login does not consume a device slot.

The request payload becomes:

```json
{
  "usr": "administrator@example.com",
  "pwd": "example-password",
  "device_id": "installation-uuid",
  "device_name": "Chrome on macOS"
}
```

### Dio Authentication

Update `lib/core/api/api_client.dart` so authenticated requests send:

```http
Authorization: token <api_key>:<api_secret>
Frappe-Authorization-Source: Flutter Device Credential
```

The current interceptor treats every path containing `flutter_utils.api.auth.` as unauthenticated. That broad check would omit credentials from `logout_device`. Replace it with an explicit guest-endpoint rule or a per-request authentication flag:

- Login, OTP send/verify, Firebase login, and public auth-settings endpoints omit credentials.
- `logout_device` requires credentials and both headers.

Keep `extra: {'withCredentials': false}` for token-authenticated web requests.

The existing `401` handler must clear only session credentials, retain the device ID, and route to login. Use a neutral expiration message unless the backend provides a reliable machine-readable revocation reason; not every `401` proves that another device caused the failure.

### Server-Side Logout

Update `AuthRepository.logout()` to:

1. Check whether local credentials exist.
2. POST to `/api/method/flutter_utils.api.auth.logout_device` with no client-supplied credential or user identifier.
3. Let the Dio interceptor attach both authentication headers.
4. Clear local session state in `finally`.
5. Disconnect or reset realtime state through the existing navigation/session lifecycle if it is not already disposed during logout.

Do not retry logout indefinitely. A failed server request must not prevent the operator from returning to the login screen.

### Realtime Authentication

Update `lib/core/realtime/frappe_realtime_service.dart` so the Socket.IO connection includes both headers in `extraHeaders`:

```dart
<String, String>{
  'Authorization': 'token $apiKey:$apiSecret',
  'Frappe-Authorization-Source': flutterDeviceCredentialSource,
}
```

Ensure reconnects read current credentials rather than retaining a revoked token after logout/login. Verify the deployed Socket.IO transport forwards custom headers for polling and WebSocket handshakes on supported native/desktop targets.

Flutter web cannot reliably attach arbitrary headers to a browser WebSocket handshake. The implementation must test the actual polling-first Socket.IO flow in the deployed web target. If the source header is not forwarded by the browser transport, realtime authentication needs a separately verified server-supported transport mechanism before rollout; do not fall back to exposing secrets in URLs.

### Assistant Iframe Authentication

`lib/features/assistant/screens/assistant_screen_web.dart` currently posts only `apiKey` and `apiSecret` to the iframe. Add the authorization source to the `frappe_llm_auth` payload:

```json
{
  "type": "frappe_llm_auth",
  "apiKey": "device-key",
  "apiSecret": "device-secret",
  "authorizationSource": "Flutter Device Credential"
}
```

The iframe consumer must add `Frappe-Authorization-Source` to its backend requests. Treat that consumer update as a deployment dependency for the assistant feature. Preserve the existing strict `postMessage` target origin and do not broaden it to `*`.

### Xealth Admin Tests

Add or extend tests for:

- Device ID generation, persistence, and reuse.
- Concurrent `getOrCreateDeviceId()` calls returning one ID.
- `clearSession()` retaining the device ID and unrelated UI preferences.
- Password login sending device fields.
- Missing or incorrect `authorization_source` rejection.
- Authenticated Dio requests carrying both headers.
- Guest auth endpoints carrying neither credential header.
- `logout_device` carrying both headers despite being in the auth module.
- Logout clearing local credentials after server success and failure.
- Access-denied cleanup revoking the newly issued device best-effort.
- A `401` clearing credentials while preserving device identity.
- Realtime options carrying the authorization-source header where the platform supports it.
- Assistant iframe messages carrying `authorizationSource` and preserving the target origin.

Run `dart format` on changed Dart files and `flutter analyze` from `flutter_apps/xealth_admin`. Run focused tests for the identity helper, preferences, auth repository, interceptor, realtime options, and iframe message builder where test seams exist.

## Xealth Employee Migration

`xealth_employee` uses mobile OTP login, a shared Dio interceptor, and local-only logout.

### Device Identity

Add `lib/core/services/device_identity_service.dart` with the same UUID and optional metadata behavior as the admin app. Keep implementation ownership inside this app unless a shared package is introduced deliberately in separate work.

Extend `lib/core/utils/shared_prefs_helper.dart` with device-ID read/write methods and a dedicated key. `clearSession()` must continue removing API credentials and employee profile data but must not remove the device ID.

### OTP Login

Keep `sendMobileLoginOtp()` unchanged because it does not issue credentials.

Update `verifyMobileLoginOtp()` in `lib/features/auth/data/auth_repository.dart`:

1. Resolve the stable device ID and optional device name before verification.
2. Send them with `mobile_no` and `otp` to `verify_mobile_login_otp`.
3. Parse and validate `authorization_source`.
4. Persist the returned API key, API secret, and identity fields as today.

The verification payload becomes:

```json
{
  "mobile_no": "+919000000000",
  "otp": "123456",
  "device_id": "installation-uuid",
  "device_name": "Pixel 11"
}
```

Do not add device parameters to the OTP send request.

### Dio Authentication

Update `lib/core/api/api_client.dart` with the same two-header authenticated contract used by the admin app.

Replace the broad `flutter_utils.api.auth.` exclusion because `logout_device` is authenticated. Use an explicit guest endpoint list or request metadata. The interceptor must attach both headers to ordinary protected requests and `logout_device`, but neither header to OTP send/verify requests.

The `401` path continues clearing the local session but must retain the installation device ID. Navigation back to authentication remains owned by the existing splash/router flow.

### Server-Side Logout

Update `AuthRepository.logout()` to call `logout_device` before local cleanup and clear local session state in `finally`.

Existing callers in `features/home/screens/home_screen.dart`, splash handling, and OTP error/recovery flows must be reviewed:

- User-initiated logout should call the server endpoint.
- Startup cleanup for invalid credentials should clear local state without repeatedly calling a protected endpoint known to be unauthorized.
- Login failure cleanup before credentials are issued should remain local-only.

Split repository methods if necessary, for example `logout()` for remote revocation and a private/local session-clear path for invalid-session recovery. Do not create logout request loops when a `401` interceptor itself clears credentials.

### Profile Session Preservation

`lib/features/profile/data/profile_repository.dart` re-saves API credentials after profile updates. Pass the persisted authorization source through `saveSession()` so profile updates cannot accidentally drop it.

### Xealth Employee Tests

Add or extend tests for:

- Device ID generation, persistence, reuse, and concurrent initialization.
- `clearSession()` removing employee/session data while retaining device identity.
- OTP send excluding device fields.
- OTP verification including device fields.
- Missing or incorrect `authorization_source` rejection.
- Protected requests carrying both authentication headers.
- OTP auth endpoints carrying neither authentication header.
- `logout_device` carrying both headers.
- User logout attempting remote revocation and always clearing local state.
- Invalid-session startup cleanup remaining local-only.
- `401` cleanup retaining device identity.
- Profile updates preserving the authentication contract.

Run `dart format` on changed Dart files and `flutter analyze` from `flutter_apps/xealth_employee`. Run focused tests for preferences, identity, auth repository, API interceptor, logout, and profile session preservation.

## Test Plan

### Settings Tests

- Default limit is `1` after migration/install.
- Saving `0` fails.
- Saving a negative value fails.
- Saving a positive value succeeds.
- Increasing the limit does not enqueue pruning.
- Reducing the limit enqueues pruning after commit.

### Credential Issuance Tests

- First device login creates one enabled device credential.
- The response includes `api_key`, `api_secret`, and `authorization_source`.
- Raw `device_id` is not stored.
- The API secret is encrypted at rest.
- Login from the same device keeps one record and rotates only that device's secret.
- Login from a second device succeeds when the limit is at least `2`.
- Credentials for both devices authenticate while within the limit.
- Credentials are isolated per user.
- Disabled users cannot receive new credentials.

### Limit Enforcement Tests

- At limit `1`, a second device revokes the first device.
- At limit `2`, a third device revokes only the oldest active device.
- Newer permitted devices remain authenticated.
- Deterministic ordering handles equal `last_login_at` values.
- Re-enabling a previously revoked device applies the limit normally.
- Two concurrent login attempts cannot leave more enabled credentials than allowed.

### Authentication Tests

- Valid credentials authenticate with both required headers.
- Omitting `Frappe-Authorization-Source` fails.
- An incorrect source fails.
- An incorrect secret fails.
- A disabled credential fails.
- A valid credential resolves exactly the credential's linked user.

### Endpoint Tests

- Password login requires and passes device identity.
- OTP login requires and passes device identity.
- OTP signup creates a user and first device credential atomically.
- Password-reset OTP does not require a device ID.
- Firebase token login requires and passes device identity.
- Firebase session login remains unchanged.
- Compatibility OTP wrappers preserve their response fields and pass device arguments.

### Logout Tests

- A device can revoke its own credential.
- The revoked credential no longer authenticates.
- Logout cannot revoke another user's credential.
- Logout using a normal User API credential is rejected.
- Repeated logout is handled safely and does not expose credential state.

### Background Pruning Tests

- Reducing from `3` to `1` keeps the newest credential for every user.
- Pruned credentials use the `Limit Reduced` reason.
- Users already within the limit are unchanged.
- Re-running the job is idempotent.
- Batch failures can be retried without over-revoking.

### Regression Tests

- OTP sending and resend cooldown behavior remain unchanged.
- Password reset remains unchanged.
- Firebase identity verification and linking remain unchanged.
- Existing authentication response identity fields remain stable.

## Documentation Changes

Update `README.md` with:

- The new `Maximum Logged-in Devices` setting.
- Required `device_id` and optional `device_name` login parameters.
- The additive `authorization_source` response field.
- Both required authenticated-request headers.
- Logout endpoint usage.
- Oldest-device eviction behavior.
- The breaking migration note for clients using User API credentials.
- A warning that browser sessions are outside this setting.

Update `flutter_apps/xealth_admin/README.md` and `flutter_apps/xealth_employee/README.md` with the local device-ID behavior, the two authentication headers, logout semantics, and upgrade expectations relevant to each app.

Example login request:

```json
{
  "usr": "user@example.com",
  "pwd": "example-password",
  "device_id": "ceceb8d4-16a7-47b9-baaa-5735b73086f8",
  "device_name": "Pixel 11"
}
```

Example authenticated request:

```http
GET /api/method/example.protected_method HTTP/1.1
Authorization: token device-key:device-secret
Frappe-Authorization-Source: Flutter Device Credential
```

## Deployment and Rollout

This is a breaking authentication-contract migration even though most response fields remain unchanged.

Recommended rollout order:

1. Implement and test the backend changes in a non-production site.
2. Run `bench --site <site> migrate` to create the setting and credential DocType.
3. Implement and test `xealth_admin` UUID persistence, password-login payload, Dio headers, Socket.IO headers, assistant iframe payload, and remote logout.
4. Implement and test `xealth_employee` UUID persistence, OTP-verification payload, Dio headers, remote logout, and invalid-session cleanup.
5. Verify `xealth_admin` realtime authentication on its deployed Flutter web transport, not only in unit tests.
6. Verify the assistant iframe consumer understands `authorizationSource` and sends the source header.
7. Run `flutter analyze` and focused tests in both Flutter apps.
8. Select either a coordinated cutover or a documented temporary compatibility window for already released clients.
9. Deploy the backend and compatible app versions in the selected order.
10. Monitor authentication failures, old-client versions, realtime connection failures, assistant failures, logout failures, and background jobs.
11. Enforce mandatory `device_id` and invalidate legacy User credentials only when compatible app adoption is sufficient.
12. Remove any temporary compatibility path after the supported upgrade window.

A strict backend-first deployment makes old clients fail new logins because they do not send `device_id`. A strict client-first deployment makes updated clients fail against the old backend because its methods do not accept the new parameters and returned API keys do not use the custom source. Therefore production requires either a coordinated cutover or an explicit temporary backend compatibility path.

For a temporary compatibility window, accept `device_id: str | None` only during rollout. Requests with a device ID use managed credentials; requests without it use the legacy contract until enforcement is activated. This temporarily allows old clients to bypass the numeric device policy, so it must have a measured adoption target, an owner, and a removal date. Once enforcement starts, `device_id` becomes mandatory and the legacy credentials are invalidated as described above.

## Observability and Support

Record enough non-secret metadata to diagnose device-limit behavior:

- User
- Optional device name
- Last login timestamp
- Enabled status
- Revocation timestamp
- Revocation reason

Do not add API keys, API secrets, raw device IDs, OTPs, or authorization headers to logs.

Background pruning failures should use a concise error title and identify only the affected user or batch where safe. The job should report aggregate processed and revoked counts through normal job logs without credential values.

## Acceptance Criteria

The implementation is complete when all of the following are true:

1. `Flutter Utils Settings` has one required numeric maximum-device setting with default `1`.
2. Every token-producing Flutter Utils login requires a stable installation device ID.
3. Each admitted device receives a distinct API key and secret.
4. Two permitted devices can authenticate concurrently without either token changing.
5. A new device over the limit revokes only the oldest active device credential.
6. Re-login on the same device does not consume another slot.
7. Lowering the limit enqueues after-commit pruning and revokes excess credentials in the background.
8. Revoked credentials fail through standard Frappe authentication.
9. A device can revoke its own credential through the logout endpoint.
10. The implementation uses Frappe's native authorization-source support without patching core authentication.
11. Legacy shared User credentials cannot silently bypass the managed-device limit after migration.
12. `xealth_admin` persists and sends one installation ID, authenticates HTTP and supported realtime requests with the source header, passes the source to the assistant iframe, and performs remote device logout.
13. `xealth_employee` persists and sends one installation ID during OTP verification, authenticates protected requests with the source header, and performs remote device logout without creating invalid-session loops.
14. Logging out or clearing an invalid session in either app retains its installation device ID.
15. Tests cover backend settings, issuance, eviction, concurrency, authentication, logout, pruning, existing auth regressions, and both clients' device/auth migrations.
16. Backend and app `README.md` files document the complete contract and rollout warning.

## Future Enhancements

The following are intentionally deferred:

- User-facing active-device list.
- Remote logout of a selected device.
- Administrator bulk revocation UI.
- Notifications when a new device logs in or an old device is evicted.
- Device-specific push-notification association.
- Per-role or per-user overrides to the global device limit.
- Inactivity-based expiration.
- A scheduled cleanup policy for old revoked credential records.

These can be added later without changing the core per-device credential model.
