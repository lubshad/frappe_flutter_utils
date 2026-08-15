import frappe


def validate() -> None:
	"""Authenticate API requests bearing a Firebase ID token."""
	auth_type, _, id_token = frappe.get_request_header("Authorization", "").partition(" ")
	if auth_type.lower() != "firebase":
		return
	if not id_token.strip():
		raise frappe.AuthenticationError

	from flutter_utils.firebase_auth import resolve_firebase_user, verify_firebase_id_token

	user = resolve_firebase_user(verify_firebase_id_token(id_token.strip()))
	form_dict = frappe.local.form_dict
	frappe.set_user(user.name)
	frappe.local.form_dict = form_dict
