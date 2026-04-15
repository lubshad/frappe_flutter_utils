import json
import random

import frappe
import phonenumbers
import requests
from frappe import _
from frappe.email.doctype.email_account.email_account import EmailAccount
from frappe.utils.password import set_encrypted_password

OTP_PURPOSES = {"login", "signup"}
OTP_CHANNELS = {"email", "mobile"}


@frappe.whitelist(allow_guest=True)
def login(usr: str, pwd: str) -> dict:
	"""
	Authenticates a user with email and password.
	Returns api_key and api_secret for subsequent authenticated requests.
	"""
	from frappe.auth import LoginManager

	login_manager = LoginManager()
	login_manager.authenticate(user=usr, pwd=pwd)
	login_manager.post_login()

	user = frappe.get_doc("User", frappe.session.user)
	return issue_user_api_credentials(user)


@frappe.whitelist(allow_guest=True)
def send_otp(
	purpose: str,
	channel: str | None = None,
	email: str | None = None,
	mobile_no: str | None = None,
	full_name: str | None = None,
) -> dict:
	"""
	Sends an OTP for login or signup using the configured delivery backend.
	Channel defaults to mobile when a mobile number is provided, otherwise email.
	"""
	settings = get_flutter_utils_settings()
	purpose = normalize_otp_purpose(purpose)
	context = resolve_otp_context(channel=channel, email=email, mobile_no=mobile_no)
	otp = generate_otp()

	if purpose == "login":
		user = validate_login_target(context)
		payload = {"otp": otp}
		recipient_name = user.full_name
	else:
		payload = validate_signup_target(context, full_name=full_name, email=email)
		payload["otp"] = otp
		recipient_name = payload["full_name"]

	cache_key = build_otp_cache_key(purpose, context["channel"], context["recipient"])
	otp_set(
		cache_key,
		json.dumps(payload),
		ttl=get_otp_ttl_seconds(),
	)

	if settings.test_mode:
		return build_otp_send_response(otp)

	try:
		deliver_otp(
			channel=context["channel"],
			recipient=context["recipient"],
			otp=otp,
			context=purpose,
			full_name=recipient_name,
		)
	except Exception:
		otp_delete(cache_key)
		raise

	return build_otp_send_response()


@frappe.whitelist(allow_guest=True)
def verify_otp(
	purpose: str,
	otp: str,
	channel: str | None = None,
	email: str | None = None,
	mobile_no: str | None = None,
) -> dict:
	"""
	Verifies an OTP for login or signup and returns auth credentials on success.
	"""
	purpose = normalize_otp_purpose(purpose)
	context = resolve_otp_context(channel=channel, email=email, mobile_no=mobile_no)
	cache_key = build_otp_cache_key(purpose, context["channel"], context["recipient"])
	raw = otp_get(cache_key)
	data = json.loads(raw) if raw else None

	if not data or data.get("otp") != otp.strip():
		frappe.throw(_("Invalid or expired OTP."))

	otp_delete(cache_key)

	if purpose == "login":
		user = (
			frappe.get_doc("User", context["recipient"])
			if context["channel"] == "email"
			else get_enabled_user_by_mobile(context["recipient"])
		)
		return issue_user_api_credentials(user)

	assert_signup_identity_available(data.get("email"), data.get("mobile_no"))
	user, api_secret = create_user_with_api_credentials(
		full_name=data["full_name"],
		email=data["email"],
		mobile_no=data.get("mobile_no"),
	)
	return build_auth_response(user, api_secret=api_secret)


@frappe.whitelist(allow_guest=True)
def send_login_otp(email: str) -> dict:
	return send_otp(purpose="login", channel="email", email=email)


@frappe.whitelist(allow_guest=True)
def verify_login_otp(email: str, otp: str) -> dict:
	return verify_otp(purpose="login", channel="email", email=email, otp=otp)


@frappe.whitelist(allow_guest=True)
def send_mobile_login_otp(mobile_no: str) -> dict:
	return send_otp(purpose="login", channel="mobile", mobile_no=mobile_no)


@frappe.whitelist(allow_guest=True)
def verify_mobile_login_otp(mobile_no: str, otp: str) -> dict:
	return verify_otp(purpose="login", channel="mobile", mobile_no=mobile_no, otp=otp)


@frappe.whitelist(allow_guest=True)
def send_signup_otp(full_name: str, email: str) -> dict:
	return send_otp(purpose="signup", channel="email", full_name=full_name, email=email)


@frappe.whitelist(allow_guest=True)
def verify_signup_otp(email: str, otp: str) -> dict:
	return verify_otp(purpose="signup", channel="email", email=email, otp=otp)


@frappe.whitelist(allow_guest=True)
def send_mobile_signup_otp(full_name: str, email: str, mobile_no: str) -> dict:
	return send_otp(
		purpose="signup",
		channel="mobile",
		full_name=full_name,
		email=email,
		mobile_no=mobile_no,
	)


@frappe.whitelist(allow_guest=True)
def verify_mobile_signup_otp(mobile_no: str, otp: str) -> dict:
	return verify_otp(purpose="signup", channel="mobile", mobile_no=mobile_no, otp=otp)


def normalize_otp_purpose(purpose: str) -> str:
	normalized = purpose.strip().lower()
	if normalized not in OTP_PURPOSES:
		frappe.throw(_("Purpose must be one of: login, signup."))
	return normalized


def resolve_otp_context(
	channel: str | None = None, email: str | None = None, mobile_no: str | None = None
) -> dict[str, str]:
	normalized_email = normalize_email(email) if email else None
	normalized_mobile = normalize_mobile_number(mobile_no) if mobile_no else None

	selected_channel = (channel or "").strip().lower() or ("mobile" if normalized_mobile else "email")
	if selected_channel not in OTP_CHANNELS:
		frappe.throw(_("Channel must be one of: email, mobile."))

	if selected_channel == "email":
		if not normalized_email:
			frappe.throw(_("Email is required for email OTP."))
		return {"channel": "email", "recipient": normalized_email}

	if not normalized_mobile:
		frappe.throw(_("Mobile number is required for mobile OTP."))
	return {"channel": "mobile", "recipient": normalized_mobile}


def validate_login_target(context: dict[str, str]):
	if context["channel"] == "email":
		enabled = frappe.db.get_value("User", context["recipient"], "enabled")
		if not enabled:
			frappe.throw(_("No active account found for this email."))
		return frappe.get_doc("User", context["recipient"])

	return get_enabled_user_by_mobile(context["recipient"])


def validate_signup_target(context: dict[str, str], full_name: str | None, email: str | None) -> dict:
	if not full_name or not full_name.strip():
		frappe.throw(_("Full name is required for signup."))

	normalized_email = normalize_email(email)
	if not normalized_email:
		frappe.throw(_("Email is required for signup."))

	assert_signup_identity_available(
		email=normalized_email,
		mobile_no=context["recipient"] if context["channel"] == "mobile" else None,
	)

	return {
		"full_name": full_name.strip(),
		"email": normalized_email,
		"mobile_no": context["recipient"] if context["channel"] == "mobile" else None,
	}


def assert_signup_identity_available(email: str | None, mobile_no: str | None = None) -> None:
	if email and frappe.db.get_value("User", email, "enabled"):
		frappe.throw(_("An account with this email already exists. Please sign in instead."))

	if mobile_no and frappe.get_all(
		"User",
		filters={"mobile_no": mobile_no, "enabled": 1},
		pluck="name",
		limit=1,
	):
		frappe.throw(_("An account with this mobile number already exists. Please sign in instead."))


def build_otp_cache_key(purpose: str, channel: str, recipient: str) -> str:
	return f"{purpose}_otp:{channel}:{recipient}"


def generate_otp() -> str:
	return str(random.randint(100000, 999999))


def _otp_cache_key(name: str) -> str:
	return f"{frappe.local.site}|{name}"


def otp_set(name: str, value: str, ttl: int) -> None:
	frappe.cache().set(_otp_cache_key(name), value, ex=ttl)


def otp_get(name: str) -> str | None:
	raw = frappe.cache().get(_otp_cache_key(name))
	return raw.decode() if raw else None


def otp_delete(name: str) -> None:
	frappe.cache().delete(_otp_cache_key(name))


def normalize_email(email: str | None) -> str | None:
	if not email:
		return None
	normalized = email.strip().lower()
	return normalized or None


def normalize_mobile_number(mobile_no: str) -> str:
	raw_mobile = mobile_no.strip()
	if not raw_mobile:
		frappe.throw(_("A valid mobile number is required."))

	settings = get_flutter_utils_settings()
	default_region = get_default_phone_region(settings)

	try:
		parsed = phonenumbers.parse(raw_mobile, default_region if not raw_mobile.startswith("+") else None)
	except phonenumbers.NumberParseException:
		frappe.throw(_("A valid mobile number is required."))

	if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
		frappe.throw(_("A valid mobile number is required."))

	return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def get_default_phone_region(settings) -> str:
	if settings.otp_default_region:
		country_code = frappe.db.get_value("Country", settings.otp_default_region, "code")
		if country_code:
			return country_code.upper()

	system_country = frappe.db.get_single_value("System Settings", "country")
	if system_country:
		country_code = frappe.db.get_value("Country", system_country, "code")
		if country_code:
			return country_code.upper()

	return "IN"


def get_enabled_user_by_mobile(mobile_no: str):
	users = frappe.get_all(
		"User",
		filters={"mobile_no": mobile_no, "enabled": 1},
		fields=["name"],
		limit=2,
	)

	if not users:
		frappe.throw(_("No active account found for this mobile number."))
	if len(users) > 1:
		frappe.throw(_("Multiple accounts use this mobile number. Please contact support."))

	return frappe.get_doc("User", users[0].name)


def issue_user_api_credentials(user) -> dict:
	api_secret = frappe.generate_hash(length=15)
	if not user.api_key:
		user.api_key = frappe.generate_hash(length=15)
		user.db_set("api_key", user.api_key, update_modified=False)
	set_encrypted_password("User", user.name, api_secret, "api_secret")
	user.api_secret = api_secret
	frappe.db.commit()
	return build_auth_response(user, api_secret=api_secret)


def create_user_with_api_credentials(full_name: str, email: str, mobile_no: str | None = None):
	user = frappe.new_doc("User")
	user.first_name = full_name
	user.email = email
	user.mobile_no = mobile_no
	user.enabled = 1
	user.new_password = frappe.generate_hash(length=20)
	user.send_welcome_email = 0
	user.api_key = frappe.generate_hash(length=15)
	api_secret = frappe.generate_hash(length=15)
	user.api_secret = api_secret
	user.insert(ignore_permissions=True)
	frappe.db.commit()
	return user, api_secret


def build_auth_response(user, api_secret: str | None = None) -> dict:
	return {
		"api_key": user.api_key,
		"api_secret": api_secret or user.get_password("api_secret"),
		"full_name": user.full_name,
		"email": user.email,
		"mobile_no": user.mobile_no,
	}


def deliver_otp(channel: str, recipient: str, otp: str, context: str, full_name: str | None = None) -> None:
	if channel == "email":
		send_otp_email(recipient, otp, context)
		return

	if channel == "mobile":
		send_otp_sms(recipient, otp, context, full_name)
		return

	frappe.throw(_("Unsupported OTP delivery channel."))


def send_otp_email(email: str, otp: str, context: str) -> None:
	settings = get_flutter_utils_settings()
	if not settings.enable_email_otp:
		frappe.throw(_("Email OTP is disabled in Flutter Utils Settings."))

	subject, message = get_email_otp_message(otp=otp, context=context)
	ensure_email_otp_delivery_is_configured()

	frappe.sendmail(recipients=[email], subject=subject, message=message, now=True)


def ensure_email_otp_delivery_is_configured() -> None:
	email_account = EmailAccount.find_outgoing(_raise_error=True)
	if email_account.service == "Sendgrid HTTP":
		api_key = email_account.get_password("password") or frappe.conf.get("sendgrid_api_key")
		if not api_key:
			frappe.throw(_("SendGrid API key is not configured for the outgoing email account."))
		return

	if email_account.service != "Frappe Mail":
		email_account.get_smtp_server()


def send_otp_sms(mobile_no: str, otp: str, context: str, full_name: str | None = None) -> None:
	settings = get_flutter_utils_settings()
	if not settings.enable_mobile_otp:
		frappe.throw(_("Mobile OTP is disabled in Flutter Utils Settings."))

	sms_gateway = (settings.sms_gateway or "").strip()
	if sms_gateway == "Twilio":
		send_twilio_sms(
			account_sid=settings.twilio_account_sid,
			auth_token=settings.get_password("twilio_auth_token"),
			from_number=settings.twilio_from_number,
			mobile_no=mobile_no,
			otp=otp,
			context=context,
			full_name=full_name,
		)
		return
	if sms_gateway == "UltraMsg":
		send_ultramsg_sms(
			base_url=settings.ultramsg_base_url,
			instance_id=settings.ultramsg_instance_id,
			token=settings.get_password("ultramsg_token"),
			mobile_no=mobile_no,
			otp=otp,
			context=context,
			full_name=full_name,
		)
		return

	frappe.throw(_("Unsupported SMS gateway. Configure Flutter Utils Settings first."))


def send_twilio_sms(
	account_sid: str | None,
	auth_token: str | None,
	from_number: str | None,
	mobile_no: str,
	otp: str,
	context: str,
	full_name: str | None = None,
) -> None:
	if not account_sid or not auth_token or not from_number:
		frappe.throw(_("Twilio is not fully configured in Flutter Utils Settings."))

	message = get_sms_otp_message(otp=otp, context=context, full_name=full_name)

	response = requests.post(
		f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
		data={"To": mobile_no, "From": from_number, "Body": message},
		auth=(account_sid, auth_token),
		timeout=15,
	)
	if response.status_code >= 400:
		frappe.log_error(
			title="Twilio OTP SMS Failed",
			message=f"Status: {response.status_code}\nResponse: {response.text}",
		)
		frappe.throw(_("Failed to send OTP SMS. Please try again later."))


def send_ultramsg_sms(
	base_url: str | None,
	instance_id: str | None,
	token: str | None,
	mobile_no: str,
	otp: str,
	context: str,
	full_name: str | None = None,
) -> None:
	if not instance_id or not token:
		frappe.throw(_("UltraMsg is not fully configured in Flutter Utils Settings."))

	message = get_sms_otp_message(otp=otp, context=context, full_name=full_name)
	api_base_url = (base_url or "https://api.ultramsg.com").rstrip("/")

	response = requests.post(
		f"{api_base_url}/{instance_id}/messages/chat",
		data={"token": token, "to": mobile_no, "body": message},
		timeout=15,
	)
	if response.status_code >= 400:
		frappe.log_error(
			title="UltraMsg OTP SMS Failed",
			message=f"Status: {response.status_code}\nResponse: {response.text}",
		)
		frappe.throw(_("Failed to send OTP message through UltraMsg. Please try again later."))


def get_flutter_utils_settings():
	try:
		return frappe.get_single("Flutter Utils Settings")
	except frappe.DoesNotExistError:
		frappe.throw(_("Flutter Utils Settings is not available. Run bench migrate first."))


def send_configured_test_message(
	settings_name: str = "Flutter Utils Settings", channel: str | None = None, recipient: str | None = None
) -> dict:
	settings = frappe.get_doc("Flutter Utils Settings", settings_name)
	test_channel = (channel or "").strip().lower()
	message = "Flutter Utils integration test message."

	if test_channel == "email":
		if not recipient:
			frappe.throw(_("Test Email is required for email integration testing."))
		if not settings.enable_email_otp:
			frappe.throw(_("Enable Email OTP before sending a test email."))
		frappe.sendmail(
			recipients=[recipient.strip()],
			subject="Flutter Utils Test Message",
			message=message,
			now=True,
		)
		return {"message": _("Test email sent successfully.")}

	if test_channel == "mobile":
		if not recipient:
			frappe.throw(_("Test Mobile Number is required for mobile integration testing."))
		normalized_mobile = normalize_mobile_number(recipient)
		deliver_test_mobile_message(settings, normalized_mobile, message)
		return {"message": _("Test mobile message sent successfully.")}

	frappe.throw(_("Select a Test Channel before sending a test message."))


def get_otp_ttl_seconds() -> int:
	settings = get_flutter_utils_settings()
	return int(settings.otp_ttl_seconds or 600)


def get_otp_template_context(otp: str, context: str, full_name: str | None = None) -> dict[str, str | int]:
	ttl_seconds = get_otp_ttl_seconds()
	return {
		"app_name": (
			frappe.db.get_single_value("Website Settings", "app_name")
			or frappe.get_system_settings("app_name")
			or frappe.local.site
		),
		"otp": otp,
		"action": _("complete your signup") if context == "signup" else _("sign in"),
		"expiry_minutes": max(1, ttl_seconds // 60),
		"expiry_seconds": ttl_seconds,
		"full_name": full_name or "",
	}


def render_setting_template(template: str, values: dict[str, str | int]) -> str:
	rendered = template
	for key, value in values.items():
		replacement = str(value)
		rendered = rendered.replace(f"{{{{ {key} }}}}", replacement)
		rendered = rendered.replace(f"{{{{{key}}}}}", replacement)
	return rendered


def get_email_otp_message(otp: str, context: str) -> tuple[str, str]:
	settings = get_flutter_utils_settings()
	template_values = get_otp_template_context(otp=otp, context=context)

	subject_template = settings.email_otp_subject_template or (
		_("Verify your email – {{ app_name }}")
		if context == "signup"
		else _("Your Login OTP – {{ app_name }}")
	)
	body_template = settings.email_otp_body_template or default_email_otp_body_template()

	return (
		render_setting_template(subject_template, template_values),
		render_setting_template(body_template, template_values),
	)


def get_sms_otp_message(otp: str, context: str, full_name: str | None = None) -> str:
	settings = get_flutter_utils_settings()
	template_values = get_otp_template_context(otp=otp, context=context, full_name=full_name)
	body_template = (
		settings.sms_otp_body_template
		or "{{ full_name }}{{ otp }} is your OTP to {{ action }} on {{ app_name }}. It expires in {{ expiry_minutes }} minutes."
	)
	return render_setting_template(body_template, template_values).strip()


def deliver_test_mobile_message(settings, mobile_no: str, message: str) -> None:
	sms_gateway = (settings.sms_gateway or "").strip()
	if sms_gateway == "Twilio":
		send_twilio_plain_message(
			account_sid=settings.twilio_account_sid,
			auth_token=settings.get_password("twilio_auth_token"),
			from_number=settings.twilio_from_number,
			mobile_no=mobile_no,
			message=message,
		)
		return
	if sms_gateway == "UltraMsg":
		send_ultramsg_plain_message(
			base_url=settings.ultramsg_base_url,
			instance_id=settings.ultramsg_instance_id,
			token=settings.get_password("ultramsg_token"),
			mobile_no=mobile_no,
			message=message,
		)
		return

	frappe.throw(_("Unsupported SMS gateway. Configure Flutter Utils Settings first."))


def send_twilio_plain_message(
	account_sid: str | None,
	auth_token: str | None,
	from_number: str | None,
	mobile_no: str,
	message: str,
) -> None:
	if not account_sid or not auth_token or not from_number:
		frappe.throw(_("Twilio is not fully configured in Flutter Utils Settings."))

	response = requests.post(
		f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
		data={"To": mobile_no, "From": from_number, "Body": message},
		auth=(account_sid, auth_token),
		timeout=15,
	)
	if response.status_code >= 400:
		frappe.log_error(
			title="Twilio Test Message Failed",
			message=f"Status: {response.status_code}\nResponse: {response.text}",
		)
		frappe.throw(_("Failed to send test message through Twilio."))


def send_ultramsg_plain_message(
	base_url: str | None,
	instance_id: str | None,
	token: str | None,
	mobile_no: str,
	message: str,
) -> None:
	if not instance_id or not token:
		frappe.throw(_("UltraMsg is not fully configured in Flutter Utils Settings."))

	api_base_url = (base_url or "https://api.ultramsg.com").rstrip("/")
	response = requests.post(
		f"{api_base_url}/{instance_id}/messages/chat",
		data={"token": token, "to": mobile_no, "body": message},
		timeout=15,
	)
	if response.status_code >= 400:
		frappe.log_error(
			title="UltraMsg Test Message Failed",
			message=f"Status: {response.status_code}\nResponse: {response.text}",
		)
		frappe.throw(_("Failed to send test message through UltraMsg."))


def build_otp_send_response(otp: str | None = None) -> dict:
	response = {"message": _("OTP sent successfully.")}
	if otp is not None:
		response["otp"] = otp
		response["test_mode"] = 1
	return response


def default_email_otp_body_template() -> str:
	return """
	<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;">
		<h2 style="color:#3525CD;margin-bottom:4px;">{{ app_name }}</h2>
		<p>Use the OTP below to {{ action }}. It expires in <strong>{{ expiry_minutes }} minutes</strong>.</p>
		<div style="font-size:40px;font-weight:bold;letter-spacing:10px;color:#3525CD;
		            background:#f0efff;padding:24px;border-radius:12px;
		            text-align:center;margin:24px 0;">
			{{ otp }}
		</div>
		<p style="color:#888;font-size:13px;">
			If you did not request this, you can safely ignore this email.
		</p>
	</div>
	"""
