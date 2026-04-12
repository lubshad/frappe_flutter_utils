# Flutter Utils

Flutter utility APIs for Frappe – exception handling and email/SMS OTP authentication.

## Features

- **Exception Handler**: Patches Frappe's default exception handler to return structured, human-readable JSON responses for Flutter clients.
- **Email OTP Authentication**: Passwordless login and signup via 6-digit OTP sent to email.
- **Mobile OTP Authentication**: Passwordless login and signup via 6-digit OTP sent to mobile using Twilio.

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `flutter_utils.api.auth.login` | Login with email + password |
| POST | `flutter_utils.api.auth.send_otp` | Generic OTP sender for `login` or `signup` using `email` or `mobile` |
| POST | `flutter_utils.api.auth.verify_otp` | Generic OTP verifier for `login` or `signup` |

Legacy wrappers still exist for backward compatibility:

- `send_login_otp`
- `verify_login_otp`
- `send_mobile_login_otp`
- `verify_mobile_login_otp`
- `send_signup_otp`
- `verify_signup_otp`
- `send_mobile_signup_otp`
- `verify_mobile_signup_otp`

## Twilio Configuration

After `bench migrate`, open `Flutter Utils Settings` from Desk and configure:

- `Enable Email OTP`
- `Enable Mobile OTP`
- `Test Mode`
- `OTP TTL (Seconds)`
- `SMS Gateway`
- `Twilio Account SID`
- `Twilio Auth Token`
- `Twilio From Number`
- `UltraMsg Base URL`
- `UltraMsg Instance ID`
- `UltraMsg Token`
- `Default Region` as a `Country` dropdown
- `Email Subject Template`
- `Email Body Template`
- `SMS Body Template`
- `Send Test Message`

Mobile numbers are validated and normalized to E.164 format before lookup, OTP delivery, and user creation. If the client sends a number without a `+` prefix, the app uses the selected `Default Region` country and falls back to `System Settings > Country`.

When `Test Mode` is enabled, OTP send APIs do not send email or SMS. They return the generated OTP directly in the JSON response as `otp`, along with `test_mode: 1`.

Templates are also settings-based now. Supported placeholders:

- `{{ app_name }}`
- `{{ otp }}`
- `{{ action }}`
- `{{ expiry_minutes }}`
- `{{ expiry_seconds }}`
- `{{ full_name }}` for SMS templates

Supported SMS gateways:

- `Twilio`
- `UltraMsg`

UltraMsg delivery uses the official endpoint:

- `POST /{instance_id}/messages/chat`
- body params: `token`, `to`, `body`
- default base URL: `https://api.ultramsg.com`

## Integration Test

`Flutter Utils Settings` now includes a Desk test section so you can verify the configured provider directly:

- click `Send Test Message`
- enter the recipient email or mobile number in the prompt

This sends a real message using the currently configured email backend or selected SMS gateway, with a built-in default message. It does not use OTP test mode.

## Generic OTP Usage

Login by email:

```json
{
  "purpose": "login",
  "channel": "email",
  "email": "user@example.com"
}
```

Login by mobile:

```json
{
  "purpose": "login",
  "channel": "mobile",
  "mobile_no": "+919876543210"
}
```

Signup with OTP sent to mobile:

```json
{
  "purpose": "signup",
  "channel": "mobile",
  "full_name": "John Doe",
  "email": "john@example.com",
  "mobile_no": "+919876543210"
}
```

Verify:

```json
{
  "purpose": "signup",
  "channel": "mobile",
  "mobile_no": "+919876543210",
  "otp": "123456"
}
```

The mobile signup API creates the Frappe `User` with:

- `email` as the user ID
- `mobile_no` populated from the verified number
- API credentials returned after verification
