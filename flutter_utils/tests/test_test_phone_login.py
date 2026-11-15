"""Isolated regression tests: no SMS providers, database writes, or site needed."""

import inspect
import json
from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from flutter_utils.api import auth
from flutter_utils.flutter_utils.doctype.flutter_utils_settings.flutter_utils_settings import (
	FlutterUtilsSettings,
)


class TestTestPhoneLogin(TestCase):
	def setUp(self) -> None:
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.settings = frappe._dict(
			enable_email_otp=1,
			enable_mobile_otp=1,
			test_phone_number="+12025550123",
			otp_length="6",
			modified="2026-10-26 12:00:00",
			test_mode=0,
		)
		self.settings.get_password = Mock(return_value="123456")
		self.entry = frappe._dict(
			name="test-row", enabled=1, channel="mobile", recipient="+12025550123", static_otp="123456"
		)
		self.settings.test_otp_accounts = [self.entry]
		self.stack.enter_context(
			patch.object(frappe.local, "session", frappe._dict(user="member@example.invalid"), create=True)
		)
		self.user = frappe._dict(
			name="reviewer@example.invalid",
			full_name="Demo Reviewer",
			enabled=1,
			user_type="Website User",
		)
		self.context = {"channel": "mobile", "recipient": self.settings.test_phone_number}
		self.cache: dict[str, str] = {}
		self.stack.enter_context(patch.object(frappe.local, "form_dict", frappe._dict(), create=True))
		self.stack.enter_context(patch.object(auth, "_", side_effect=lambda text: text))
		self.stack.enter_context(patch.object(frappe, "throw", side_effect=frappe.ValidationError))
		self.stack.enter_context(patch.object(auth, "get_flutter_utils_settings", return_value=self.settings))
		self.stack.enter_context(patch.object(auth, "get_default_phone_region", return_value="IN"))
		self.stack.enter_context(patch.object(auth, "resolve_otp_context", return_value=self.context))
		self.stack.enter_context(patch.object(auth, "validate_login_target", return_value=self.user))
		self.stack.enter_context(patch.object(auth, "get_enabled_user_by_mobile", return_value=self.user))
		self.stack.enter_context(patch.object(auth, "get_enabled_user_by_email", return_value=self.user))
		self.roles = self.stack.enter_context(patch.object(frappe, "get_roles", return_value=["All"]))
		self.cooldown = self.stack.enter_context(patch.object(auth, "enforce_otp_resend_cooldown"))
		self.record_cooldown = self.stack.enter_context(patch.object(auth, "record_otp_resend_cooldown"))
		self.stack.enter_context(patch.object(auth, "get_otp_ttl_seconds", return_value=300))
		self.stack.enter_context(patch.object(frappe.utils, "get_fullname", return_value="Test User"))
		self.stack.enter_context(patch.object(auth, "generate_otp", return_value="987654"))
		self.stack.enter_context(patch.object(auth, "otp_set", side_effect=self._store))
		self.stack.enter_context(patch.object(auth, "otp_get", side_effect=self.cache.get))
		self.stack.enter_context(
			patch.object(auth, "otp_delete", side_effect=lambda key: self.cache.pop(key, None))
		)
		self.deliver = self.stack.enter_context(patch.object(auth, "deliver_otp"))
		self.stack.enter_context(patch.object(auth, "hash_device_id"))
		self.stack.enter_context(patch.object(auth, "normalize_device_name"))
		self.issue = self.stack.enter_context(
			patch.object(auth, "issue_device_api_credentials", return_value={"ok": True})
		)

	def _store(self, key: str, value: str, ttl: int) -> None:
		self.assertEqual(ttl, 300)
		self.cache[key] = value

	def _send(self, purpose: str = "login", **kwargs) -> dict:
		return inspect.unwrap(auth.send_otp)(
			purpose=purpose,
			channel=self.context["channel"],
			mobile_no=self.context["recipient"] if self.context["channel"] == "mobile" else None,
			email=kwargs.pop(
				"email", self.context["recipient"] if self.context["channel"] == "email" else None
			),
			**kwargs,
		)

	def _verify(self, code: str = "123456", purpose: str = "login", **kwargs) -> dict:
		return inspect.unwrap(auth.verify_otp)(
			purpose=purpose,
			channel=self.context["channel"],
			mobile_no=self.context["recipient"],
			otp=code,
			device_id="demo-device",
			**kwargs,
		)

	def test_static_challenge_skips_delivery_and_hides_code_even_in_global_test_mode(self) -> None:
		for global_test_mode in (0, 1):
			with self.subTest(global_test_mode=global_test_mode):
				self.settings.test_mode = global_test_mode
				response = self._send()
				self.assertEqual(set(response), {"message"})
				payload = json.loads(next(iter(self.cache.values())))
				self.assertEqual(payload["otp"], "123456")
				self.assertIn("test_otp_override", payload)
		self.deliver.assert_not_called()
		self.cooldown.assert_called_with("login", "mobile", self.context["recipient"])
		self.record_cooldown.assert_called_with("login", "mobile", self.context["recipient"])

	def test_success_uses_existing_device_credentials_and_consumes_challenge(self) -> None:
		self._send()
		self.assertEqual(self._verify(), {"ok": True})
		self.issue.assert_called_once_with(self.user, "demo-device", None)
		with self.assertRaises(frappe.ValidationError):
			self._verify()

	def test_normal_challenges_keep_working_when_demo_configuration_changes(self) -> None:
		self.entry.enabled = 0
		self._send()
		self.entry.enabled = 1
		self.settings.modified = "2026-10-26 14:00:00"
		self.assertEqual(self._verify("987654"), {"ok": True})

	def test_cooldown_and_missing_account_fail_before_storing_or_delivering(self) -> None:
		self.cooldown.side_effect = frappe.ValidationError
		with self.assertRaises(frappe.ValidationError):
			self._send()
		self.cooldown.side_effect = None
		with patch.object(auth, "validate_login_target", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				self._send()
		self.assertFalse(self.cache)
		self.deliver.assert_not_called()
		self.record_cooldown.assert_not_called()

	def test_disabling_account_after_send_rejects_verification(self) -> None:
		self._send()
		with patch.object(auth, "validate_login_target", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				self._verify()
		self.issue.assert_not_called()

	def test_wrong_missing_and_expired_codes_do_not_issue_credentials(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			self._verify()
		self._send()
		with self.assertRaises(frappe.ValidationError):
			self._verify("000000")
		self.cache.clear()  # Simulate Redis TTL expiry.
		with self.assertRaises(frappe.ValidationError):
			self._verify()
		self.issue.assert_not_called()

	def test_disabling_or_changing_configuration_invalidates_pending_challenges(self) -> None:
		for target, field, value in (
			(self.entry, "enabled", 0),
			(self.settings, "modified", "2026-10-26 13:00:00"),
			(self.entry, "recipient", "+919400797246"),
		):
			with self.subTest(field=field):
				self._send()
				original = target[field]
				target[field] = value
				with self.assertRaises(frappe.ValidationError):
					self._verify()
				target[field] = original
				self.cache.clear()
		self.issue.assert_not_called()

	def test_rotating_static_code_invalidates_pending_challenge(self) -> None:
		self._send()
		self.entry.static_otp = "654321"
		with self.assertRaises(frappe.ValidationError):
			self._verify()
		self.issue.assert_not_called()

	def test_account_reassignment_rejects_challenge_but_user_type_is_unrestricted(self) -> None:
		self._send()
		self.user.name = "different@example.invalid"
		with self.assertRaises(frappe.ValidationError):
			self._verify()
		self._send()
		self.user.user_type = "System User"
		self.assertEqual(self._verify(), {"ok": True})

	def test_other_numbers_and_disabled_option_keep_normal_delivery(self) -> None:
		for field, value in (("enabled", 0), ("recipient", "+919400797246")):
			with self.subTest(field=field):
				original = self.entry[field]
				self.entry[field] = value
				self._send()
				self.deliver.assert_called_with(
					channel="mobile",
					recipient=self.context["recipient"],
					otp="987654",
					context="login",
					full_name=self.user.full_name,
				)
				self.entry[field] = original

	def test_channel_matching_is_exact(self) -> None:
		self.assertIsNone(
			auth._get_test_otp_entry(
				self.settings, {"channel": "email", "recipient": self.context["recipient"]}
			)
		)

	def test_no_additional_role_restrictions(self) -> None:
		self.user.user_type = "System User"
		self.roles.return_value = ["System Manager"]
		self._send()
		self.assertEqual(self._verify(), {"ok": True})
		self.roles.assert_not_called()

	def test_malformed_or_wrong_length_static_code_fails_closed(self) -> None:
		for code in ("", "1234", "abcdef", "\uff11\uff12\uff13\uff14\uff15\uff16"):
			with self.subTest(code=code):
				self.entry.static_otp = code
				with self.assertRaises(frappe.ValidationError):
					self._send()
		self.deliver.assert_not_called()

	def test_public_settings_do_not_expose_demo_configuration(self) -> None:
		with patch.object(auth, "get_default_phone_region", return_value="IN"):
			result = inspect.unwrap(auth.get_otp_auth_settings)()
		self.assertEqual(set(result), {"otp_length", "otp_resend_cooldown_seconds", "otp_default_region"})

	def test_settings_validation_normalizes_number_and_rejects_bad_configuration(self) -> None:
		with patch.object(auth, "get_default_phone_region", return_value="IN"):
			self.entry.recipient = "+1 202 555 0123"
			FlutterUtilsSettings._validate_test_otp_accounts(self.settings)
		self.assertEqual(self.entry.recipient, "+12025550123")
		self.settings.enable_mobile_otp = 0
		FlutterUtilsSettings._validate_test_otp_accounts(self.settings)
		for field, value in (("recipient", "2025550123"),):
			with self.subTest(field=field):
				original = self.entry[field]
				self.entry[field] = value
				with self.assertRaises(frappe.ValidationError):
					FlutterUtilsSettings._validate_test_otp_accounts(self.settings)
				self.entry[field] = original
		self.entry.static_otp = "1234"
		with self.assertRaises(frappe.ValidationError):
			FlutterUtilsSettings._validate_test_otp_accounts(self.settings)

	def test_restricted_phone_works_without_sms_and_requires_single_use_challenge(self) -> None:
		self.settings.enable_mobile_otp = 0
		with self.assertRaises(frappe.ValidationError):
			self._verify()
		self._send()
		self.assertEqual(self._verify(), {"ok": True})
		with self.assertRaises(frappe.ValidationError):
			self._verify()
		self.deliver.assert_not_called()

	def test_disabled_channel_rejects_unlisted_numbers(self) -> None:
		self.settings.enable_mobile_otp = 0
		self.context["recipient"] = "+12025550124"
		with self.assertRaises(frappe.ValidationError):
			self._send()
		with self.assertRaises(frappe.ValidationError):
			self._verify()
		self.deliver.assert_not_called()
		self.issue.assert_not_called()

	def test_pre_switch_unbound_challenge_cannot_authenticate_reviewer(self) -> None:
		self.entry.enabled = 0
		self._send()
		self.entry.enabled = 1
		self.settings.enable_mobile_otp = 0
		with self.assertRaises(frappe.ValidationError):
			self._verify("987654")
		self.issue.assert_not_called()

	def test_restricted_mode_requires_existing_enabled_user(self) -> None:
		self.settings.enable_mobile_otp = 0
		with patch.object(auth, "validate_login_target", side_effect=frappe.ValidationError):
			with self.assertRaises(frappe.ValidationError):
				self._send()
		self.assertFalse(self.cache)
		self.deliver.assert_not_called()

	def test_restricted_mode_does_not_change_email_or_real_sms_availability(self) -> None:
		self.settings.enable_mobile_otp = 0
		self.assertIsNone(
			auth.require_otp_channel_available(
				self.settings, {"channel": "email", "recipient": "member@example.invalid"}
			)
		)
		self.settings.enable_mobile_otp = 1
		self.assertIsNone(
			auth.require_otp_channel_available(
				self.settings, {"channel": "mobile", "recipient": "+12025550124"}
			)
		)

	def test_multiple_entries_and_disabled_email_channel(self) -> None:
		email_entry = frappe._dict(
			name="email-row", enabled=1, channel="email", recipient="demo@example.com", static_otp="001234"
		)
		self.settings.test_otp_accounts.append(email_entry)
		self.settings.enable_email_otp = 0
		self.settings.enable_mobile_otp = 0
		self._send()
		self.context.update(channel="email", recipient=email_entry.recipient)
		for mode in (0, 1):
			self.settings.test_mode = mode
			self.assertEqual(set(self._send()), {"message"})
			with self.assertRaises(frappe.ValidationError):
				self._verify("123456")
			self.assertEqual(self._verify("001234"), {"ok": True})
		self.deliver.assert_not_called()

	def test_signup_override_creates_real_account_on_both_channels(self) -> None:
		for channel, recipient in (("mobile", "+12025550123"), ("email", "new@example.com")):
			with (
				self.subTest(channel=channel),
				patch.object(auth, "assert_signup_identity_available") as available,
				patch.object(auth, "create_user", return_value=self.user) as create,
			):
				self.entry.update(channel=channel, recipient=recipient)
				self.context.update(channel=channel, recipient=recipient)
				self.settings.enable_mobile_otp = self.settings.enable_email_otp = 0
				self._send("signup", full_name="New User", email="new@example.com")
				self.assertEqual(self._verify(purpose="signup"), {"ok": True})
				create.assert_called_once_with(
					full_name="New User",
					email="new@example.com",
					mobile_no=recipient if channel == "mobile" else None,
				)
				self.assertEqual(available.call_count, 2)
		self.deliver.assert_not_called()

	def test_email_password_reset_uses_override_and_normal_password_update(self) -> None:
		self.entry.update(channel="email", recipient="demo@example.com")
		self.context.update(channel="email", recipient=self.entry.recipient)
		self.settings.enable_email_otp = 0
		with patch.object(auth, "set_user_password") as reset:
			self._send("reset_password")
			self.assertEqual(
				self._verify(purpose="reset_password", new_password="new-test-password"),
				{"message": "Password has been reset successfully."},
			)
			reset.assert_called_once_with(self.user, "new-test-password")
		self.deliver.assert_not_called()

	def test_override_does_not_enable_unsupported_mobile_password_reset(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			self._send("reset_password")
		self.assertFalse(self.cache)

	def test_contact_verification_keeps_auth_requirement_and_consumes_challenge(self) -> None:
		self.settings.enable_mobile_otp = 0
		with patch.object(frappe.local, "session", frappe._dict(user="Guest")):
			with self.assertRaises(frappe.ValidationError):
				self._send("verify_mobile")
		self._send("verify_mobile")
		self.assertEqual(
			self._verify(purpose="verify_mobile"), {"verified": True, "mobile_no": self.context["recipient"]}
		)
		with self.assertRaises(frappe.ValidationError):
			self._verify(purpose="verify_mobile")
		self.deliver.assert_not_called()

	def test_invalid_signup_inputs_still_fail(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			self._send("signup")
		self.assertFalse(self.cache)
		self.deliver.assert_not_called()

	def test_email_normalization_duplicates_and_invalid_inputs(self) -> None:
		self.entry.update(channel="email", recipient=" Demo@Example.COM ", static_otp="001234")
		FlutterUtilsSettings._validate_test_otp_accounts(self.settings)
		self.assertEqual(self.entry.recipient, "demo@example.com")
		self.assertEqual(self.entry.static_otp, "001234")
		duplicate = frappe._dict(self.entry)
		duplicate.recipient = "DEMO@example.com"
		duplicate.enabled = 0
		self.settings.test_otp_accounts.append(duplicate)
		with self.assertRaises(frappe.ValidationError):
			FlutterUtilsSettings._validate_test_otp_accounts(self.settings)
		self.settings.test_otp_accounts.pop()
		for channel, recipient in (("email", "invalid"), ("sms", "demo@example.com")):
			self.entry.update(channel=channel, recipient=recipient)
			with self.assertRaises(frappe.ValidationError):
				FlutterUtilsSettings._validate_test_otp_accounts(self.settings)

	def test_deleted_entry_and_legacy_challenge_fail_closed(self) -> None:
		self._send()
		self.settings.test_otp_accounts.clear()
		with self.assertRaises(frappe.ValidationError):
			self._verify()
		self.settings.test_otp_accounts.append(self.entry)
		self._send()
		key = next(iter(self.cache))
		self.cache[key] = json.dumps({"otp": "123456", "test_phone_login": "legacy"})
		with self.assertRaises(frappe.ValidationError):
			self._verify()

	def test_settings_permissions_and_plain_text_field_contract(self) -> None:
		from pathlib import Path

		root = Path(auth.__file__).parents[1] / "flutter_utils" / "doctype"
		settings_meta = json.loads(
			(root / "flutter_utils_settings" / "flutter_utils_settings.json").read_text()
		)
		self.assertEqual([p["role"] for p in settings_meta["permissions"]], ["System Manager"])
		child = json.loads((root / "test_otp_account" / "test_otp_account.json").read_text())
		self.assertFalse(child["permissions"])
		self.assertEqual(
			next(f for f in child["fields"] if f["fieldname"] == "static_otp")["fieldtype"], "Data"
		)

	def test_test_only_configuration_does_not_require_an_enabled_provider(self) -> None:
		self.settings.update(
			maximum_logged_in_devices=1,
			otp_ttl_seconds=300,
			enable_mobile_otp=0,
			enable_email_otp=0,
			enable_firebase_auth=0,
		)
		self.settings._validate_app_settings = Mock()
		self.settings._validate_firebase_settings = Mock()
		self.settings._validate_test_otp_accounts = Mock()
		FlutterUtilsSettings.validate(self.settings)
		self.settings._validate_test_otp_accounts.assert_called_once()
		self.entry.enabled = 0
		with self.assertRaises(frappe.ValidationError):
			FlutterUtilsSettings.validate(self.settings)

	def test_session_login_keeps_existing_auth_contract(self) -> None:
		self._send()
		with patch.object(auth, "create_browser_session", return_value={"session": True}) as create:
			self.assertEqual(self._verify(auth_mode="session"), {"session": True})
			create.assert_called_once_with(self.user)
		self.issue.assert_not_called()

	def test_test_challenges_cannot_cross_purposes(self) -> None:
		self._send()
		with self.assertRaises(frappe.ValidationError):
			self._verify(purpose="signup")
		self.assertEqual(self._verify(), {"ok": True})

	def test_legacy_mobile_gate_supports_overrides_without_account_lookup(self) -> None:
		self.settings.enable_mobile_otp = 0
		for purpose in ("login", "signup", "verify_mobile"):
			self.assertTrue(auth.require_mobile_otp_available(self.settings, purpose, self.context))
		self.entry.enabled = 0
		with self.assertRaises(frappe.ValidationError):
			auth.require_mobile_otp_available(self.settings, "login", self.context)
