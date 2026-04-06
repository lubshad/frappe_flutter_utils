import json
import random

import frappe
from frappe import _


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

	api_secret = frappe.generate_hash(length=15)
	if not user.api_key:
		user.api_key = frappe.generate_hash(length=15)
	user.api_secret = api_secret
	user.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"api_key": user.api_key,
		"api_secret": api_secret,
		"full_name": user.full_name,
		"email": user.email,
	}


@frappe.whitelist(allow_guest=True)
def send_login_otp(email: str) -> dict:
	"""
	Generates a 6-digit OTP and emails it to the user for passwordless login.
	The OTP expires in 10 minutes.
	"""
	email = email.strip().lower()

	enabled = frappe.db.get_value("User", email, "enabled")
	if not enabled:
		frappe.throw(_("No active account found for this email."))

	otp = str(random.randint(100000, 999999))
	otp_set(f"login_otp:{email}", otp)

	send_otp_email(email, otp, "login")
	return {"message": _("OTP sent successfully.")}


@frappe.whitelist(allow_guest=True)
def verify_login_otp(email: str, otp: str) -> dict:
	"""
	Verifies the OTP for a login request.
	On success, returns api_key and api_secret for authenticated requests.
	"""
	email = email.strip().lower()
	stored_otp = otp_get(f"login_otp:{email}")

	if not stored_otp or stored_otp != otp.strip():
		frappe.throw(_("Invalid or expired OTP."))

	otp_delete(f"login_otp:{email}")

	user = frappe.get_doc("User", email)
	api_secret = frappe.generate_hash(length=15)
	if not user.api_key:
		user.api_key = frappe.generate_hash(length=15)
	user.api_secret = api_secret
	user.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"api_key": user.api_key,
		"api_secret": api_secret,
		"full_name": user.full_name,
		"email": user.email,
	}


@frappe.whitelist(allow_guest=True)
def send_signup_otp(full_name: str, email: str) -> dict:
	"""
	Validates the email is new, stores signup details and OTP in cache, and emails the OTP.
	The OTP expires in 10 minutes.
	"""
	email = email.strip().lower()

	if frappe.db.get_value("User", email, "enabled"):
		frappe.throw(_("An account with this email already exists. Please sign in instead."))

	otp = str(random.randint(100000, 999999))
	otp_set(f"signup_otp:{email}", json.dumps({"full_name": full_name.strip(), "otp": otp}))

	send_otp_email(email, otp, "signup")
	return {"message": _("OTP sent successfully.")}


@frappe.whitelist(allow_guest=True)
def verify_signup_otp(email: str, otp: str) -> dict:
	"""
	Verifies the OTP for a signup request and creates a new enabled User account.
	On success, returns api_key and api_secret for authenticated requests.
	"""
	email = email.strip().lower()
	raw = otp_get(f"signup_otp:{email}")
	data = json.loads(raw) if raw else None

	if not data or data.get("otp") != otp.strip():
		frappe.throw(_("Invalid or expired OTP."))

	otp_delete(f"signup_otp:{email}")

	user = frappe.new_doc("User")
	user.first_name = data["full_name"]
	user.email = email
	user.enabled = 1
	user.new_password = frappe.generate_hash(length=20)
	user.send_welcome_email = 0

	# Generate API credentials
	api_secret = frappe.generate_hash(length=15)
	user.api_key = frappe.generate_hash(length=15)
	user.api_secret = api_secret

	user.insert(ignore_permissions=True)
	frappe.db.commit()

	return {
		"api_key": user.api_key,
		"api_secret": api_secret,
		"full_name": user.full_name,
		"email": user.email,
	}


# ---------------------------------------------------------------------------
# OTP cache helpers
# ---------------------------------------------------------------------------

OTP_TTL_SECONDS = 600  # 10 minutes


def _otp_cache_key(name: str) -> str:
	"""Builds a site-scoped Redis key that is session-user-independent."""
	return f"{frappe.local.site}|{name}"


def otp_set(name: str, value: str, ttl: int = OTP_TTL_SECONDS) -> None:
	frappe.cache().set(_otp_cache_key(name), value, ex=ttl)


def otp_get(name: str) -> str | None:
	raw = frappe.cache().get(_otp_cache_key(name))
	return raw.decode() if raw else None


def otp_delete(name: str) -> None:
	frappe.cache().delete(_otp_cache_key(name))


def send_otp_email(email: str, otp: str, context: str) -> None:
	"""
	Sends an OTP email using the 'OTP Email Template' if it exists,
	otherwise falls back to a hardcoded format.
	"""
	app_name = (
		frappe.db.get_single_value("Website Settings", "app_name")
		or frappe.get_system_settings("app_name")
		or frappe.local.site
	)
	action = _("complete your signup") if context == "signup" else _("sign in")

	template_name = _("OTP Email Template")
	if frappe.db.exists("Email Template", template_name):
		email_template = frappe.get_doc("Email Template", template_name)
		formatted = email_template.get_formatted_email({
			"otp": otp,
			"action": action,
			"app_name": app_name
		})
		subject = formatted["subject"]
		message = formatted["message"]
	else:
		# Fallback to hardcoded style
		subject = (
			_("Verify your email – {0}").format(app_name)
			if context == "signup"
			else _("Your Login OTP – {0}").format(app_name)
		)
		message = otp_email_body(otp, context, app_name)

	frappe.sendmail(
		recipients=[email],
		subject=subject,
		message=message,
		now=True,
	)


def otp_email_body(otp: str, context: str, app_name: str) -> str:
	action = _("complete your signup") if context == "signup" else _("sign in")
	return f"""
	<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;">
		<h2 style="color:#3525CD;margin-bottom:4px;">{app_name}</h2>
		<p>Use the OTP below to {action}. It expires in <strong>10 minutes</strong>.</p>
		<div style="font-size:40px;font-weight:bold;letter-spacing:10px;color:#3525CD;
		            background:#f0efff;padding:24px;border-radius:12px;
		            text-align:center;margin:24px 0;">
			{otp}
		</div>
		<p style="color:#888;font-size:13px;">
			If you did not request this, you can safely ignore this email.
		</p>
	</div>
	"""
