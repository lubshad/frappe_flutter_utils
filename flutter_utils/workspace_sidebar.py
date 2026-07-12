from __future__ import annotations

from typing import Any
from urllib.parse import quote

import frappe
from frappe.desk.desktop import get_workspaces
from frappe.desk.utils import slug
from frappe.utils import cint
from frappe.utils.data import get_url_to_workspace


def redirect_to_workspace_sidebar(login_manager: Any) -> None:
	"""Set the login destination for users who explicitly bypass the Desk icon grid."""
	user = login_manager.user
	if not user or user == "Guest":
		return

	settings = frappe.db.get_value(
		"User",
		user,
		["user_type", "default_workspace_sidebar", "redirect_to_workspace_sidebar_on_login"],
		as_dict=True,
	)
	if (
		not settings
		or settings.user_type != "System User"
		or not settings.default_workspace_sidebar
		or not cint(settings.redirect_to_workspace_sidebar_on_login)
	):
		return

	route = get_workspace_sidebar_route(settings.default_workspace_sidebar)
	if route:
		frappe.local.flags.home_page = route


def get_workspace_sidebar_route(sidebar_name: str) -> str | None:
	"""Return the first permitted sidebar destination with its sidebar context."""
	if not frappe.db.exists("Workspace Sidebar", sidebar_name):
		return None

	sidebar = frappe.get_doc("Workspace Sidebar", sidebar_name)
	allowed_workspaces = {workspace.name for workspace in get_workspaces()["pages"]}
	for item in sidebar.items:
		if item.type != "Link" or not sidebar.is_item_allowed(
			item.link_to, item.link_type, allowed_workspaces
		):
			continue

		route = _get_item_route(item)
		if route:
			return _add_sidebar_context(route, sidebar_name)

	return None


def get_default_workspace_sidebar(user: str | None = None) -> dict[str, Any] | None:
	"""Return the authenticated user's assigned sidebar with permitted items only."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None

	sidebar_name = frappe.db.get_value("User", user, "default_workspace_sidebar")
	if not sidebar_name or not frappe.db.exists("Workspace Sidebar", sidebar_name):
		return None

	sidebar = frappe.get_doc("Workspace Sidebar", sidebar_name)
	allowed_workspaces = {workspace.name for workspace in get_workspaces()["pages"]}
	items = _get_permitted_sidebar_items(sidebar, allowed_workspaces)
	return {
		"name": sidebar.name,
		"title": sidebar.title,
		"header_icon": sidebar.header_icon,
		"items": items,
	}


def _get_permitted_sidebar_items(sidebar: Any, allowed_workspaces: set[str]) -> list[dict[str, Any]]:
	"""Keep section breaks only when they contain at least one permitted child link."""
	items: list[dict[str, Any]] = []
	pending_section: dict[str, Any] | None = None
	for item in sidebar.items:
		if item.type == "Section Break":
			pending_section = _serialize_sidebar_item(item)
			continue

		if item.type != "Link" or not sidebar.is_item_allowed(
			item.link_to, item.link_type, allowed_workspaces
		):
			continue

		if pending_section and item.child:
			items.append(pending_section)
			pending_section = None
		items.append(_serialize_sidebar_item(item))

	return items


def _serialize_sidebar_item(item: Any) -> dict[str, Any]:
	return {
		"type": item.type,
		"label": item.label,
		"icon": item.icon,
		"link_type": item.link_type,
		"link_to": item.link_to,
		"url": item.url,
		"child": item.child,
		"indent": item.indent,
		"collapsible": item.collapsible,
		"keep_closed": item.keep_closed,
	}


def _get_item_route(item: Any) -> str | None:
	link_type = item.link_type
	if link_type == "URL":
		return item.url or None

	if link_type == "DocType":
		meta = frappe.get_meta(item.link_to)
		if meta.issingle:
			return f"/desk/{slug(item.link_to)}/{quote(item.link_to)}"
		return f"/desk/{slug(item.link_to)}"

	if link_type == "Page":
		return f"/desk/{slug(item.link_to)}"

	if link_type == "Dashboard":
		return f"/desk/dashboard-view/{quote(item.link_to)}"

	if link_type == "Report":
		report = frappe.db.get_value("Report", item.link_to, ["report_type", "ref_doctype"], as_dict=True)
		if not report:
			return None
		if report.report_type in {"Query Report", "Script Report"}:
			return f"/desk/query-report/{quote(item.link_to)}"
		if report.ref_doctype:
			return f"/desk/{slug(report.ref_doctype)}/view/report/{quote(item.link_to)}"
		return f"/desk/report/{quote(item.link_to)}"

	if link_type == "Workspace":
		workspace = frappe.db.get_value("Workspace", item.link_to, ["name", "public"], as_dict=True)
		if workspace:
			return get_url_to_workspace(workspace.name, workspace.public)

	return None


def _add_sidebar_context(route: str, sidebar_name: str) -> str:
	if not route.startswith("/"):
		return route
	separator = "&" if "?" in route else "?"
	return f"{route}{separator}sidebar={quote(sidebar_name)}"
