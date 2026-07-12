"""Add opt-in Desk sidebar redirect settings to the core User DocType."""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute() -> None:
	if not frappe.db.table_exists("User") or not frappe.db.table_exists("Workspace Sidebar"):
		return

	create_custom_fields(
		{
			"User": [
				{
					"fieldname": "default_workspace_sidebar",
					"fieldtype": "Link",
					"label": "Default Workspace Sidebar",
					"options": "Workspace Sidebar",
					"insert_after": "default_workspace",
				},
				{
					"fieldname": "redirect_to_workspace_sidebar_on_login",
					"fieldtype": "Check",
					"label": "Redirect to Workspace Sidebar on Login",
					"description": "Skip Desk icons and open the first permitted sidebar item after login.",
					"depends_on": "eval:doc.default_workspace_sidebar",
					"insert_after": "default_workspace_sidebar",
				},
			]
		},
		ignore_validate=True,
		update=True,
	)
	frappe.clear_cache(doctype="User")
	frappe.db.commit()
