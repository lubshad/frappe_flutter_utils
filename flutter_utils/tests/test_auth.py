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


class TestBrowserSessionAuthentication(FrappeTestCase):
	def test_guest_session_context_is_anonymous(self) -> None:
		original_user = frappe.session.user
		try:
			frappe.set_user("Guest")
			self.assertEqual(
				auth.get_session_context(),
				{"authenticated": False, "auth_mode": "session"},
			)
		finally:
			frappe.set_user(original_user)

	def test_requires_password_when_email_login_setting_is_enabled(self) -> None:
		settings = frappe._dict(require_password_for_email_login_otp=1)
		context = {"channel": "email", "recipient": "user@example.com"}
		user = frappe._dict(name="user@example.com")

		with self.assertRaises(frappe.AuthenticationError):
			auth.validate_login_password(user, context, None, settings)

	def test_validates_password_without_creating_a_session(self) -> None:
		settings = frappe._dict(require_password_for_email_login_otp=1)
		context = {"channel": "email", "recipient": "user@example.com"}
		user = frappe._dict(name="user@example.com")

		with patch("frappe.auth.LoginManager") as login_manager_class:
			verified = auth.validate_login_password(user, context, "correct-password", settings)

		self.assertTrue(verified)
		login_manager_class.return_value.authenticate.assert_called_once_with(
			user="user@example.com", pwd="correct-password"
		)
		login_manager_class.return_value.post_login.assert_not_called()

	def test_session_mode_does_not_require_device_credentials(self) -> None:
		user = frappe._dict(name="user@example.com")
		payload = '{"otp": "1234", "password_verified": true}'

		with (
			patch(
				"flutter_utils.api.auth.resolve_otp_context",
				return_value={"channel": "email", "recipient": "user@example.com"},
			),
			patch("flutter_utils.api.auth.otp_get", return_value=payload),
			patch("flutter_utils.api.auth.otp_delete"),
			patch("flutter_utils.api.auth.get_enabled_user_by_email", return_value=user),
			patch(
				"flutter_utils.api.auth.get_flutter_utils_settings",
				return_value=frappe._dict(require_password_for_email_login_otp=1),
			),
			patch(
				"flutter_utils.api.auth.create_browser_session",
				return_value={"auth_mode": "session", "user": user.name},
			),
			patch("flutter_utils.api.auth.hash_device_id") as hash_device_id,
		):
			result = auth.verify_otp(
				purpose="login",
				channel="email",
				email="user@example.com",
				otp="1234",
				auth_mode="session",
			)

		self.assertEqual(result, {"auth_mode": "session", "user": "user@example.com"})
		hash_device_id.assert_not_called()

	def test_token_mode_remains_the_default(self) -> None:
		user = frappe._dict(name="user@example.com")
		payload = '{"otp": "1234", "password_verified": false}'

		with (
			patch(
				"flutter_utils.api.auth.resolve_otp_context",
				return_value={"channel": "email", "recipient": "user@example.com"},
			),
			patch("flutter_utils.api.auth.otp_get", return_value=payload),
			patch("flutter_utils.api.auth.otp_delete"),
			patch("flutter_utils.api.auth.get_enabled_user_by_email", return_value=user),
			patch(
				"flutter_utils.api.auth.get_flutter_utils_settings",
				return_value=frappe._dict(require_password_for_email_login_otp=0),
			),
			patch("flutter_utils.api.auth.hash_device_id"),
			patch("flutter_utils.api.auth.normalize_device_name"),
			patch(
				"flutter_utils.api.auth.issue_device_api_credentials",
				return_value={"api_key": "key", "api_secret": "secret"},
			) as issue_credentials,
		):
			result = auth.verify_otp(
				purpose="login",
				channel="email",
				email="user@example.com",
				otp="1234",
				device_id="00000000-0000-4000-8000-000000000000",
			)

		self.assertEqual(result["api_key"], "key")
		issue_credentials.assert_called_once()
