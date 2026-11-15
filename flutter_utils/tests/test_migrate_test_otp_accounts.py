"""Isolated migration contract tests; no live site or secrets."""

from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from flutter_utils.patches.v1_0 import migrate_test_otp_accounts as migration


class TestMigrateTestOTPAccounts(TestCase):
	def setUp(self) -> None:
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.settings = frappe._dict(
			name="Flutter Utils Settings",
			test_phone_number="+12025550123",
			enable_test_phone_login=1,
			test_otp_accounts=[],
		)
		self.settings.get_password = Mock(return_value="001234")
		self.row = Mock()
		self.settings.append = Mock(side_effect=self._append)
		self.stack.enter_context(patch.object(migration.frappe, "reload_doc"))
		self.stack.enter_context(patch.object(migration.frappe, "get_single", return_value=self.settings))
		self.stack.enter_context(patch.object(migration.frappe, "db", Mock()))
		self.stack.enter_context(patch.object(migration.frappe, "clear_document_cache"))
		self.stack.enter_context(patch.object(migration.frappe, "throw", side_effect=frappe.ValidationError))
		self.remove_password = self.stack.enter_context(patch.object(migration, "remove_encrypted_password"))
		self.stack.enter_context(
			patch("flutter_utils.api.auth.normalize_mobile_number", return_value="+12025550123")
		)

	def _append(self, field: str, values: dict) -> Mock:
		self.settings[field].append(frappe._dict(values))
		return self.row

	def test_preserves_code_and_enabled_state_and_is_idempotent(self) -> None:
		migration.execute()
		self.assertEqual(
			self.settings.test_otp_accounts,
			[dict(enabled=1, channel="mobile", recipient="+12025550123", static_otp="001234")],
		)
		self.row.db_insert.assert_called_once()
		self.remove_password.assert_called_once_with(
			"Flutter Utils Settings", self.settings.name, "test_phone_otp"
		)
		migration.execute()
		self.row.db_insert.assert_called_once()

	def test_preserves_disabled_entry(self) -> None:
		self.settings.enable_test_phone_login = 0
		migration.execute()
		self.assertEqual(self.settings.test_otp_accounts[0].enabled, 0)

	def test_existing_new_entry_wins_without_overwriting_it(self) -> None:
		self.settings.test_otp_accounts = [
			frappe._dict(channel="mobile", recipient="+12025550123", static_otp="654321")
		]
		migration.execute()
		self.settings.append.assert_not_called()
		self.assertEqual(self.settings.test_otp_accounts[0].static_otp, "654321")

	def test_fresh_install_has_nothing_to_migrate(self) -> None:
		self.settings.test_phone_number = None
		self.settings.enable_test_phone_login = 0
		self.settings.get_password.return_value = None
		migration.execute()
		self.settings.append.assert_not_called()

	def test_incomplete_enabled_legacy_configuration_is_not_silently_lost(self) -> None:
		self.settings.get_password.return_value = None
		with self.assertRaises(frappe.ValidationError):
			migration.execute()
		self.remove_password.assert_not_called()
