from unittest.mock import MagicMock, patch

import frappe
from frappe.auth import validate_api_key_secret
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import get_decrypted_password

from flutter_utils.device_credentials import (
	AUTHORIZATION_SOURCE,
	hash_device_id,
	issue_device_api_credentials,
	logout_current_device,
	prune_device_credentials,
)


class TestDeviceCredentials(FrappeTestCase):
	def setUp(self) -> None:
		self.original_login_manager = getattr(frappe.local, "login_manager", None)
		frappe.local.login_manager = MagicMock(user=frappe.session.user)
		self.user_name = "flutter-device-test@example.invalid"
		frappe.delete_doc_if_exists("User", self.user_name, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": self.user_name,
				"first_name": "Flutter Device Test",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		self.user = user
		self.original_limit = frappe.db.get_single_value(
			"Flutter Utils Settings", "maximum_logged_in_devices"
		)

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.set_single_value(
			"Flutter Utils Settings",
			"maximum_logged_in_devices",
			self.original_limit or 1,
		)
		for name in frappe.get_all(
			AUTHORIZATION_SOURCE,
			filters={"user": self.user_name},
			pluck="name",
		):
			frappe.delete_doc(AUTHORIZATION_SOURCE, name, force=True)
		frappe.delete_doc_if_exists("User", self.user_name, force=True)
		frappe.local.login_manager = self.original_login_manager

	def test_issues_distinct_credentials_within_limit(self) -> None:
		self._set_limit(2)
		first = issue_device_api_credentials(self.user, "device-one", "Phone")
		second = issue_device_api_credentials(self.user, "device-two", "Tablet")

		self.assertNotEqual(first["api_key"], second["api_key"])
		self.assertEqual(first["authorization_source"], AUTHORIZATION_SOURCE)
		self.assertEqual(
			frappe.db.count(AUTHORIZATION_SOURCE, {"user": self.user_name, "enabled": 1}),
			2,
		)
		self.assertFalse(frappe.db.exists(AUTHORIZATION_SOURCE, {"device_id_hash": "device-one"}))

	def test_same_device_rotates_secret_without_consuming_slot(self) -> None:
		first = issue_device_api_credentials(self.user, "same-device")
		second = issue_device_api_credentials(self.user, "same-device")

		self.assertEqual(first["api_key"], second["api_key"])
		self.assertNotEqual(first["api_secret"], second["api_secret"])
		self.assertEqual(frappe.db.count(AUTHORIZATION_SOURCE, {"user": self.user_name}), 1)
		self.assertEqual(
			get_decrypted_password(
				AUTHORIZATION_SOURCE,
				frappe.db.get_value(AUTHORIZATION_SOURCE, {"api_key": second["api_key"]}, "name"),
				"api_secret",
			),
			second["api_secret"],
		)

	def test_new_device_revokes_oldest_at_limit(self) -> None:
		self._set_limit(2)
		first = issue_device_api_credentials(self.user, "oldest")
		second = issue_device_api_credentials(self.user, "middle")
		third = issue_device_api_credentials(self.user, "newest")

		self.assertEqual(
			frappe.db.get_value(AUTHORIZATION_SOURCE, {"api_key": first["api_key"]}, "enabled"),
			0,
		)
		self.assertEqual(
			frappe.db.get_value(
				AUTHORIZATION_SOURCE,
				{"api_key": first["api_key"]},
				"revocation_reason",
			),
			"Device Limit",
		)
		self.assertEqual(
			frappe.db.count(AUTHORIZATION_SOURCE, {"user": self.user_name, "enabled": 1}),
			2,
		)
		self.assertTrue(second["api_key"])
		self.assertTrue(third["api_key"])

	def test_frappe_authenticates_custom_authorization_source(self) -> None:
		credentials = issue_device_api_credentials(self.user, "authenticated-device")
		original_user = frappe.session.user
		try:
			frappe.set_user("Guest")
			frappe.local.login_manager.user = "Guest"
			validate_api_key_secret(
				credentials["api_key"],
				credentials["api_secret"],
				AUTHORIZATION_SOURCE,
			)
			self.assertEqual(frappe.session.user, self.user_name)
		finally:
			frappe.set_user(original_user)

	def test_logout_revokes_calling_credential(self) -> None:
		credentials = issue_device_api_credentials(self.user, "logout-device")
		with patch(
			"frappe.get_request_header",
			side_effect=lambda name, default="": {
				"Frappe-Authorization-Source": AUTHORIZATION_SOURCE,
				"Authorization": f"token {credentials['api_key']}:{credentials['api_secret']}",
			}.get(name, default),
		):
			original_user = frappe.session.user
			try:
				frappe.set_user(self.user_name)
				response = logout_current_device()
			finally:
				frappe.set_user(original_user)

		self.assertEqual(response["message"], "Device logged out successfully.")
		self.assertEqual(
			frappe.db.get_value(AUTHORIZATION_SOURCE, {"api_key": credentials["api_key"]}, "enabled"),
			0,
		)

	def test_pruning_keeps_newest_credentials(self) -> None:
		self._set_limit(3)
		first = issue_device_api_credentials(self.user, "first")
		issue_device_api_credentials(self.user, "second")
		third = issue_device_api_credentials(self.user, "third")

		with patch("frappe.db.commit"):
			prune_device_credentials(1)

		self.assertEqual(
			frappe.db.get_value(AUTHORIZATION_SOURCE, {"api_key": first["api_key"]}, "enabled"),
			0,
		)
		self.assertEqual(
			frappe.db.get_value(AUTHORIZATION_SOURCE, {"api_key": third["api_key"]}, "enabled"),
			1,
		)

	def test_rejects_missing_and_oversized_device_ids(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			hash_device_id("")
		with self.assertRaises(frappe.ValidationError):
			hash_device_id("x" * 129)

	def _set_limit(self, limit: int) -> None:
		frappe.db.set_single_value("Flutter Utils Settings", "maximum_logged_in_devices", limit)
