# Managed Device Realtime Authentication

No changes to Frappe core or its Socket.IO middleware are required.

For managed credentials, Socket.IO clients send:

```http
Authorization: FlutterDevice <api_key>:<api_secret>
```

Stock Frappe Socket.IO forwards Authorization during authentication and subsequent
permission checks. The registered `flutter_utils.auth.validate` hook validates
this scheme against enabled Flutter Device Credential records, checks the user's
enabled status, and compares the secret before setting the request user. Frappe's
normal request permissions and IP restrictions still apply.

Do not send credentials in query strings. Browser clients must use a transport
that supports the Authorization header (polling-first Socket.IO), or a trusted
server-side proxy. Browser WebSocket handshakes cannot attach arbitrary headers.
Verify the deployed transport and CORS configuration before rollout.

Ordinary HTTP requests, including logout_device, continue using `Authorization:
token ...` with `Frappe-Authorization-Source: Flutter Device Credential`. Legacy
User credentials retain the token scheme for realtime as well.

Deploy flutter_utils before the updated realtime clients and restart Python
workers. If an earlier framework middleware patch was running, revert it and
restart Socket.IO too. Authentication is checked on connection and permission
requests; this does not introduce proactive disconnection of already joined
sockets when a credential is revoked.
