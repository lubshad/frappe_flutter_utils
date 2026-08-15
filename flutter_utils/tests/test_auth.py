from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

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
