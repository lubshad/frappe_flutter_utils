from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from flutter_utils.workspace_sidebar import get_default_workspace_sidebar, get_workspace_sidebar_route


class TestWorkspaceSidebarRedirect(FrappeTestCase):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.sidebar_name = "Test Flutter Utils Sidebar"
		self.original_default_sidebar = frappe.db.get_value(
			"User", "Administrator", "default_workspace_sidebar"
		)
		frappe.delete_doc_if_exists("Workspace Sidebar", self.sidebar_name, force=True)

	def tearDown(self) -> None:
		frappe.db.set_value("User", "Administrator", "default_workspace_sidebar", self.original_default_sidebar)
		frappe.delete_doc_if_exists("Workspace Sidebar", self.sidebar_name, force=True)

	def test_uses_first_permitted_link_and_sidebar_context(self) -> None:
		sidebar = frappe.get_doc(
			{
				"doctype": "Workspace Sidebar",
				"title": self.sidebar_name,
				"items": [
					{"type": "Section Break", "label": "Profiles", "link_type": "DocType"},
					{"type": "Link", "label": "Users", "link_type": "DocType", "link_to": "User"},
				],
			}
		).insert(ignore_permissions=True)

		self.assertEqual(
			get_workspace_sidebar_route(sidebar.name),
			f"/desk/user?sidebar={self.sidebar_name.replace(' ', '%20')}",
		)

	def test_returns_none_for_missing_sidebar(self) -> None:
		self.assertIsNone(get_workspace_sidebar_route("Missing Flutter Utils Sidebar"))

	def test_serializes_default_sidebar_items(self) -> None:
		sidebar = frappe.get_doc(
			{
				"doctype": "Workspace Sidebar",
				"title": self.sidebar_name,
				"items": [
					{"type": "Section Break", "label": "Profiles", "link_type": "DocType"},
					{
						"type": "Link",
						"label": "Users",
						"link_type": "DocType",
						"link_to": "User",
						"child": 1,
					},
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("User", "Administrator", "default_workspace_sidebar", sidebar.name)

		result = get_default_workspace_sidebar("Administrator")

		self.assertEqual(result["name"], sidebar.name)
		self.assertEqual([item["label"] for item in result["items"]], ["Profiles", "Users"])
