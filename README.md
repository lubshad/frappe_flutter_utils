# Flutter Utils

Flutter utility APIs for Frappe – exception handling and email OTP authentication.

## Features

- **Exception Handler**: Patches Frappe's default exception handler to return structured, human-readable JSON responses for Flutter clients.
- **Email OTP Authentication**: Passwordless login and signup via 6-digit OTP sent to email.

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `flutter_utils.api.auth.login` | Login with email + password |
| POST | `flutter_utils.api.auth.send_login_otp` | Send OTP for passwordless login |
| POST | `flutter_utils.api.auth.verify_login_otp` | Verify login OTP, returns API keys |
| POST | `flutter_utils.api.auth.send_signup_otp` | Send OTP for new account signup |
| POST | `flutter_utils.api.auth.verify_signup_otp` | Verify signup OTP, creates account |
