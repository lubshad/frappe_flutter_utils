from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from flutter_utils.api import auth
from flutter_utils.auth import validate


class TestFirebaseAuthHook(FrappeTestCase):
	def test_preserves_parsed_request_arguments_when_setting_user(self) -> None:
		original_user = frappe.session.user
		form_dict = frappe._dict({"answers": "serialized-answers"})
		frappe.local.form_dict = form_dict

		try:
			with (
				patch("frappe.get_request_header", return_value="Firebase valid-token"),
				patch(
					"flutter_utils.firebase_auth.verify_firebase_id_token",
					return_value={"uid": "firebase-user"},
				),
				patch(
					"flutter_utils.firebase_auth.resolve_firebase_user",
					return_value=frappe._dict(name="firebase-user@example.invalid"),
				),
			):
				validate()

			self.assertIs(frappe.local.form_dict, form_dict)
			self.assertEqual(frappe.form_dict.answers, "serialized-answers")
		finally:
			frappe.set_user(original_user)

	def test_ignores_other_authorization_schemes(self) -> None:
		with (
			patch("frappe.get_request_header", return_value="token api-key:api-secret"),
			patch("flutter_utils.firebase_auth.verify_firebase_id_token") as verify_token,
		):
			validate()

		verify_token.assert_not_called()

	def test_rejects_missing_firebase_token(self) -> None:
		with (
			patch("frappe.get_request_header", return_value="Firebase "),
			self.assertRaises(frappe.AuthenticationError),
		):
			validate()


class TestOtpCooldown(FrappeTestCase):
	def test_does_not_start_cooldown_when_login_target_is_invalid(self) -> None:
		with (
			patch(
				"flutter_utils.api.auth.get_flutter_utils_settings", return_value=frappe._dict(test_mode=True)
			),
			patch(
				"flutter_utils.api.auth.resolve_otp_context",
				return_value={"channel": "mobile", "recipient": "+919400797246"},
			),
			patch("flutter_utils.api.auth.enforce_otp_resend_cooldown"),
			patch("flutter_utils.api.auth.validate_login_target", side_effect=frappe.ValidationError()),
			patch("flutter_utils.api.auth.record_otp_resend_cooldown") as record_cooldown,
			self.assertRaises(frappe.ValidationError),
		):
			auth.send_otp(purpose="login", channel="mobile", mobile_no="+919400797246")

		record_cooldown.assert_not_called()

	def test_starts_cooldown_after_otp_is_prepared_in_test_mode(self) -> None:
		with (
			patch(
				"flutter_utils.api.auth.get_flutter_utils_settings", return_value=frappe._dict(test_mode=True)
			),
			patch(
				"flutter_utils.api.auth.resolve_otp_context",
				return_value={"channel": "mobile", "recipient": "+919400797246"},
			),
			patch("flutter_utils.api.auth.enforce_otp_resend_cooldown"),
			patch("flutter_utils.api.auth.generate_otp", return_value="1234"),
			patch(
				"flutter_utils.api.auth.validate_login_target",
				return_value=frappe._dict(full_name="Test User"),
			),
			patch("flutter_utils.api.auth.otp_set") as store_otp,
			patch("flutter_utils.api.auth.record_otp_resend_cooldown") as record_cooldown,
		):
			auth.send_otp(purpose="login", channel="mobile", mobile_no="+919400797246")

		store_otp.assert_called_once()
		record_cooldown.assert_called_once_with("login", "mobile", "+919400797246")
