"""Move sidebar defaults to native Workspaces and remove obsolete User fields."""

from __future__ import annotations

import frappe

_CUSTOM_FIELDS = (
	"default_workspace_sidebar",
	"redirect_to_workspace_sidebar_on_login",
)


def execute() -> None:
	if not frappe.db.table_exists("User"):
		return

	legacy_sidebar_field = frappe.db.get_value(
		"Custom Field", {"dt": "User", "fieldname": "default_workspace_sidebar"}
	)
	if legacy_sidebar_field and frappe.db.has_column("User", "default_workspace_sidebar"):
		users = frappe.get_all(
			"User",
			filters={"default_workspace_sidebar": ("is", "set")},
			fields=["name", "default_workspace", "default_workspace_sidebar"],
		)
		for user in users:
			if user.default_workspace or not user.default_workspace_sidebar:
				continue
			frappe.db.set_value(
				"User",
				user.name,
				"default_workspace",
				user.default_workspace_sidebar,
				update_modified=False,
			)
			frappe.clear_cache(user=user.name)

	for fieldname in _CUSTOM_FIELDS:
		custom_field = frappe.db.get_value(
			"Custom Field",
			{"dt": "User", "fieldname": fieldname},
		)
		if custom_field:
			frappe.delete_doc("Custom Field", custom_field, force=True, ignore_permissions=True)

	frappe.clear_cache(doctype="User")
	frappe.db.commit()
