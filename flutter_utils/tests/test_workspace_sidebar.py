from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from flutter_utils.workspace_sidebar import (
	get_default_workspace_sidebar,
	get_sidebar_for_default_workspace,
)


class TestDefaultWorkspaceSidebar(FrappeTestCase):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.sidebar_name = "Test Flutter Utils Sidebar"
		self.alternative_sidebar_name = "Test Alternative Sidebar"
		self.original_default_workspace = frappe.db.get_value("User", "Administrator", "default_workspace")
		frappe.delete_doc_if_exists("Workspace", self.sidebar_name, force=True)
		frappe.delete_doc_if_exists("Workspace Sidebar", self.alternative_sidebar_name, force=True)
		frappe.delete_doc_if_exists("Workspace Sidebar", self.sidebar_name, force=True)

	def tearDown(self) -> None:
		frappe.db.set_value("User", "Administrator", "default_workspace", self.original_default_workspace)
		frappe.delete_doc_if_exists("Workspace Sidebar", self.sidebar_name, force=True)
		frappe.delete_doc_if_exists("Workspace Sidebar", self.alternative_sidebar_name, force=True)
		frappe.delete_doc_if_exists("Workspace", self.sidebar_name, force=True)

	def test_resolves_sidebar_linked_to_default_workspace(self) -> None:
		self._create_workspace()
		sidebar = frappe.get_doc(
			{
				"doctype": "Workspace Sidebar",
				"title": self.sidebar_name,
				"items": [
					{
						"type": "Link",
						"label": "Home",
						"link_type": "Workspace",
						"link_to": self.sidebar_name,
					},
					{"type": "Link", "label": "Users", "link_type": "DocType", "link_to": "User"},
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("User", "Administrator", "default_workspace", self.sidebar_name)

		self.assertEqual(get_sidebar_for_default_workspace("Administrator").name, sidebar.name)

	def test_prefers_same_named_sidebar_when_multiple_sidebars_link_workspace(self) -> None:
		self._create_workspace()
		for sidebar_name in (self.alternative_sidebar_name, self.sidebar_name):
			frappe.get_doc(
				{
					"doctype": "Workspace Sidebar",
					"title": sidebar_name,
					"items": [
						{
							"type": "Link",
							"label": "Home",
							"link_type": "Workspace",
							"link_to": self.sidebar_name,
						}
					],
				}
			).insert(ignore_permissions=True)
		frappe.db.set_value("User", "Administrator", "default_workspace", self.sidebar_name)

		self.assertEqual(
			get_sidebar_for_default_workspace("Administrator").name,
			self.sidebar_name,
		)

	def test_returns_none_without_default_workspace(self) -> None:
		frappe.db.set_value("User", "Administrator", "default_workspace", None)
		self.assertIsNone(get_sidebar_for_default_workspace("Administrator"))

	def test_serializes_default_sidebar_items(self) -> None:
		self._create_workspace()
		sidebar = frappe.get_doc(
			{
				"doctype": "Workspace Sidebar",
				"title": self.sidebar_name,
				"items": [
					{
						"type": "Link",
						"label": "Home",
						"link_type": "Workspace",
						"link_to": self.sidebar_name,
					},
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
		frappe.db.set_value("User", "Administrator", "default_workspace", sidebar.name)

		result = get_default_workspace_sidebar("Administrator")

		self.assertEqual(result["name"], sidebar.name)
		self.assertEqual([item["label"] for item in result["items"]], ["Home", "Profiles", "Users"])

	def _create_workspace(self) -> None:
		frappe.get_doc(
			{
				"doctype": "Workspace",
				"label": self.sidebar_name,
				"title": self.sidebar_name,
				"public": 1,
			}
		).insert(ignore_permissions=True)
