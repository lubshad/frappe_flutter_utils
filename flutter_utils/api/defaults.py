from typing import Any

import frappe
from frappe import _


@frappe.whitelist()
def get_session_defaults() -> dict[str, Any]:
	"""Return generic Frappe defaults context for authenticated Flutter clients."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Authentication required."), frappe.AuthenticationError)

	return {
		"user": user,
		"user_fullname": frappe.get_cached_value("User", user, "full_name") or user,
		"defaults": frappe.defaults.get_defaults(user),
		"sysdefaults": frappe.defaults.get_defaults_for("__default"),
		"user_permissions": frappe.defaults.get_user_permissions(user),
	}


@frappe.whitelist()
def get_new_doc(doctype: str) -> dict[str, Any]:
	"""Return a new unsaved document with Frappe's native defaults applied."""
	doctype = (doctype or "").strip()
	if not doctype:
		frappe.throw(_("DocType is required."))
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("DocType {0} does not exist.").format(doctype))

	frappe.has_permission(doctype, "create", throw=True)

	from frappe.model.create_new import get_new_doc as make_new_doc

	return make_new_doc(doctype, as_dict=True)
