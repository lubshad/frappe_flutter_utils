"""Preserve the legacy test phone configuration when moving to multi-channel overrides."""

import frappe
from frappe import _
from frappe.utils.password import remove_encrypted_password


def execute() -> None:
	frappe.reload_doc("flutter_utils", "doctype", "test_otp_account")
	frappe.reload_doc("flutter_utils", "doctype", "flutter_utils_settings")
	settings = frappe.get_single("Flutter Utils Settings")
	phone = settings.get("test_phone_number")
	code = settings.get_password("test_phone_otp", raise_exception=False)
	if phone and code:
		from flutter_utils.api.auth import normalize_mobile_number

		try:
			phone = normalize_mobile_number(phone)
		except frappe.ValidationError:
			if settings.get("enable_test_phone_login"):
				frappe.throw(
					_(
						"Cannot migrate enabled Test Phone Login: invalid phone number. "
						"Correct the legacy test phone number in Flutter Utils Settings and retry migration."
					)
				)
			frappe.logger("flutter_utils").warning(
				"Skipping invalid legacy test phone configuration because Test Phone Login is disabled."
			)
			phone = None
		if phone and not any(
			row.channel == "mobile" and row.recipient == phone for row in settings.test_otp_accounts
		):
			row = settings.append(
				"test_otp_accounts",
				{
					"enabled": int(settings.get("enable_test_phone_login") or 0),
					"channel": "mobile",
					"recipient": phone,
					"static_otp": code,
				},
			)
			# Migrate data without revalidating unrelated provider configuration.
			row.db_insert()
	elif settings.get("enable_test_phone_login"):
		frappe.throw("Cannot migrate enabled Test Phone Login: missing phone number or OTP.")

	for field, value in (("enable_test_phone_login", 0), ("test_phone_number", ""), ("test_phone_otp", "")):
		frappe.db.set_single_value("Flutter Utils Settings", field, value)
	remove_encrypted_password("Flutter Utils Settings", settings.name, "test_phone_otp")
	frappe.clear_document_cache("Flutter Utils Settings", settings.name)
