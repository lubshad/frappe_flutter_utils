"""Move the latest push registration onto its credential before retiring the DocType."""

import hashlib

import frappe


def execute() -> None:
	legacy = "Flutter Push Registration"
	if not frappe.db.exists("DocType", legacy):
		return
	frappe.reload_doc("flutter_utils", "doctype", "flutter_device_credential")
	credentials = {
		row.name: row
		for row in frappe.get_all(
			"Flutter Device Credential", fields=["name", "user", "enabled", "push_last_seen_at"]
		)
	}
	seen: set[str] = set()
	for row in frappe.get_all(
		legacy,
		fields=["device_credential", "user", "app", "platform", "token", "active", "last_seen_at"],
		order_by="active desc, last_seen_at desc, modified desc, name desc",
	):
		device = credentials.get(row.device_credential)
		if not device or device.user != row.user or device.name in seen:
			continue
		seen.add(device.name)
		if device.push_last_seen_at or not row.token:
			continue
		token_hash = hashlib.sha256(row.token.encode()).hexdigest()
		if frappe.db.exists("Flutter Device Credential", {"fcm_token_hash": token_hash}):
			continue
		frappe.db.set_value(
			"Flutter Device Credential",
			device.name,
			{
				"app": row.app,
				"platform": row.platform,
				"fcm_token": row.token,
				"fcm_token_hash": token_hash,
				"push_enabled": int(bool(row.active and device.enabled)),
				"push_last_seen_at": row.last_seen_at,
			},
			update_modified=False,
		)
	# Frappe retains the physical legacy table; only obsolete metadata is retired.
	frappe.delete_doc("DocType", legacy, force=True, ignore_permissions=True)
