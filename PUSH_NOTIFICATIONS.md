# Firebase push notifications

`flutter_utils` owns managed-device push registration and queued FCM delivery.
Applications retain their own recipient authorization, notification preferences,
inbox records, and deep-link payloads.

## Setup

1. Run `bench --site <site> migrate` after deploying the app.
2. In **Flutter Utils Settings**, enable **Firebase Push** and configure the
   existing **Firebase Project ID** and encrypted **Firebase Service Account JSON**.
   Firebase Authentication can be disabled when another login provider is used.
3. The service account must have FCM sending permission for the clients' Firebase
   project. The worker uses this site-specific connection; no
   `GOOGLE_APPLICATION_CREDENTIALS` environment variable is needed.
4. Restart workers when deploying the new Python code. Keep a queue worker running.

## Device APIs

Both endpoints require managed-device authentication:

```http
Authorization: token <device_api_key>:<device_api_secret>
Frappe-Authorization-Source: Flutter Device Credential
```

Cookie-only sessions, legacy User tokens, Firebase bearer authentication, disabled
credentials, and guest requests are rejected. The server resolves device ownership
from the authenticated credential; clients do not supply a user or credential name.

```http
POST /api/method/flutter_utils.api.push_notifications.register_push_device
Content-Type: application/json

{"token":"<FCM registration token>","platform":"android","app":"my_app"}
```

Returns the standard Frappe `message` containing `{"name":"...","active":true}`.
Platforms: android, ios, web, macos, windows, linux (delivery still depends on the
client platform's FCM support). Application identifiers allow letters, numbers,
underscores, dots, and hyphens, up to 140 characters.

Register after authenticated startup and when the FCM token changes. Refresh
deactivates the previous registration for that credential/application. A token can
move to the newly authenticated device/account on the same installation.

```http
POST /api/method/flutter_utils.api.push_notifications.unregister_push_device
Content-Type: application/json

{"token":"<FCM registration token>"}
```

Unregistration is idempotent and restricted to the current credential. Logout,
device-limit eviction, limit reduction, and disabling a credential deactivate its
registrations. Workers also filter disabled credentials and disabled users.

## Backend use

```python
from flutter_utils.push_notifications import enqueue_push_notifications

enqueue_push_notifications(
    users=[recipient_user],
    title="Request approved",
    body="Your request was approved. Open the app to review the details.",
    app="my_app",
    data={"document_type": "My Request", "document_name": request.name},
)
```

Call this from trusted backend code after validating recipients and persisting
local state. It queues after commit. It is not a public arbitrary-send endpoint.
Delivery is best-effort: FCM sends use batches of 500, unregistered tokens are
deactivated, and failures are recorded in Error Log without provider secrets.
There is no automatic delivery retry or per-message delivery-status DocType.

## Xealth transition

Xealth's existing registration endpoint paths delegate to these same APIs and
require the same managed-device headers. Existing queued Xealth worker paths also
delegate to the shared worker. Xealth retains route-to-app mapping and preferences.

`Xealth Push Device` records are retained but no longer used for delivery. They
have no credential identity and are not matched by user alone. Existing devices
must register again during authenticated startup to update their
`Flutter Device Credential` push fields. Enable Firebase Push after configuring the
service account; the setting defaults to off.

## Credential-owned push tokens

Each `Flutter Device Credential` stores one current token (`fcm_token`), its unique
hash, `app`, `platform`, `push_enabled`, and `push_last_seen_at`. Registration
updates this credential and returns `{name: <credential name>, active: true}`.
Endpoint paths and request bodies are unchanged. Registering another app/token
on the same credential replaces the previous one. Apps must use their own
persisted installation UUID. Token reassignment clears the previous credential's
token so account switching cannot leave duplicate recipients.

Unregistration and invalid-token responses disable push only. Credential logout,
revocation, and device-limit eviction disable push too; signing in again requires
fresh push registration. Delivery remains a background job and filters by app.

Migration copies the latest active legacy registration per credential (or latest
inactive record if none is active), preserving disabled credential state, and
retires the `Flutter Push Registration` DocType. Frappe retains the legacy table
for recovery; it is no longer read or written by push APIs.
