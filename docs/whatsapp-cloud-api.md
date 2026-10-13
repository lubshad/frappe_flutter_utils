# WhatsApp Cloud API (Meta)

Flutter Utils can deliver Mobile OTPs and integration test messages through Meta
WhatsApp Cloud API. It is one of the `SMS Gateway` options, alongside `Twilio` and
`UltraMsg`, so existing OTP flows, cooldowns, and templates are unchanged.

## Configuration

1. Open `Flutter Utils Settings`.
2. In the `Authentication` tab, enable `Enable Mobile OTP`.
3. In the `Email & SMS` tab, select `WhatsApp (Meta)` as the `SMS Gateway`.
4. Open the `Meta` tab and fill in:

| Field | Required | Purpose |
|---|---|---|
| `Phone Number ID` | yes | WhatsApp business phone number ID used as the sender. |
| `Access Token` | yes | Meta access token. Stored encrypted and never returned by public APIs. |
| `OTP Template Name` | yes | Approved Meta template with a single body text parameter for the OTP. |
| `OTP Template Language` | no | Template language code. Defaults to `en_US`. |
| `Graph API Version` | no | Graph API version. Defaults to `v23.0`. |

`Test Meta Connection` calls the Graph API with the configured phone number ID and
access token and reports the resolved number on success.

## Delivery

OTP messages are sent as a WhatsApp **template** message:

```json
{
	"messaging_product": "whatsapp",
	"to": "919876543210",
	"type": "template",
	"template": {
		"name": "otp_login",
		"language": {"code": "en_US"},
		"components": [
			{"type": "body", "parameters": [{"type": "text", "text": "1234"}]}
		]
	}
}
```

The named template must accept one body text parameter. Business-initiated
conversations must start from an approved template, so a template is required for
OTP delivery even when `Test Mode` is off.

`Send Test Message` sends a free-form `text` message instead. Meta only delivers
free-form text inside an open 24-hour customer service window, so a test can fail
with a delivery error for a number that has never messaged the business; that is a
Meta policy, not a Flutter Utils misconfiguration.

Numbers are normalized to E.164 first and then sent without the leading `+`, as
required by the Cloud API. Failed requests are logged with the Graph API response
and surfaced to the client as a generic delivery error.
