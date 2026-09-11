import hmac

import frappe
from frappe.utils.password import get_decrypted_password


def validate() -> None:
	"""Authenticate Firebase and managed-device realtime authorization schemes."""
	auth_type, _, id_token = frappe.get_request_header("Authorization", "").partition(" ")
	if auth_type.lower() == "flutterdevice":
		api_key, separator, api_secret = id_token.partition(":")
		if not separator or not api_key or not api_secret or ":" in api_secret:
			raise frappe.AuthenticationError
		credential = frappe.db.get_value(
			"Flutter Device Credential",
			{"api_key": api_key, "enabled": 1},
			["name", "user"],
			as_dict=True,
		)
		if not credential or not frappe.db.get_value("User", credential.user, "enabled"):
			raise frappe.AuthenticationError
		secret = get_decrypted_password(
			"Flutter Device Credential", credential.name, "api_secret", raise_exception=False
		)
		if not secret or not hmac.compare_digest(secret.encode(), api_secret.encode()):
			raise frappe.AuthenticationError
		form_dict = frappe.local.form_dict
		frappe.set_user(credential.user)
		frappe.local.form_dict = form_dict
		return
	if auth_type.lower() != "firebase":
		return
	if not id_token.strip():
		raise frappe.AuthenticationError

	from flutter_utils.firebase_auth import resolve_firebase_user, verify_firebase_id_token

	user = resolve_firebase_user(verify_firebase_id_token(id_token.strip()))
	form_dict = frappe.local.form_dict
	frappe.set_user(user.name)
	frappe.local.form_dict = form_dict
