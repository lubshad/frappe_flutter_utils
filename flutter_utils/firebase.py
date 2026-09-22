"""Site-configured Firebase connection shared by authentication and messaging."""

import hashlib
from typing import Any

import frappe
from firebase_admin import credentials, get_app, initialize_app


def get_firebase_app(settings: Any | None = None) -> Any:
	from flutter_utils.firebase_auth import parse_service_account_json

	settings = settings or frappe.get_single("Flutter Utils Settings")
	service_account = parse_service_account_json(settings.get_password("firebase_service_account_json"))
	project_id = str(settings.firebase_project_id or "").strip()
	if not project_id or project_id != service_account["project_id"]:
		raise ValueError("Firebase project configuration is invalid.")
	fingerprint = ":".join(
		[
			frappe.local.site,
			project_id,
			str(service_account.get("client_email") or ""),
			str(service_account.get("private_key_id") or ""),
		]
	)
	name = f"flutter-utils-{hashlib.sha256(fingerprint.encode()).hexdigest()[:24]}"
	try:
		return get_app(name)
	except ValueError:
		return initialize_app(credentials.Certificate(service_account), {"projectId": project_id}, name=name)
