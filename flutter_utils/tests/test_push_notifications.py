from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.auth import validate_api_key_secret
from frappe.tests.utils import FrappeTestCase

from flutter_utils.device_credentials import (
	AUTHORIZATION_SOURCE,
	issue_device_api_credentials,
	logout_current_device,
)
from flutter_utils.push_notifications import (
	REGISTRATION_DOCTYPE,
	enqueue_push_notifications,
	register_push_device,
	send_push_notifications,
	unregister_push_device,
)


class TestPushNotifications(FrappeTestCase):
	def setUp(self) -> None:
		self.old_user = frappe.session.user
		self.old_manager = getattr(frappe.local, "login_manager", None)
		frappe.local.login_manager = Mock(user="Administrator")
		self.user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"push-{frappe.generate_hash(length=10)}@example.invalid",
				"first_name": "Push Test",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		self.limit = frappe.db.get_single_value("Flutter Utils Settings", "maximum_logged_in_devices")
		frappe.db.set_single_value("Flutter Utils Settings", "maximum_logged_in_devices", 3)
		self.credentials = issue_device_api_credentials(self.user, "push-device-one")
		self.second = issue_device_api_credentials(self.user, "push-device-two")
		self.headers = {
			"Frappe-Authorization-Source": AUTHORIZATION_SOURCE,
			"Authorization": f"token {self.credentials['api_key']}:{self.credentials['api_secret']}",
		}
		self.header_patch = patch(
			"frappe.get_request_header", side_effect=lambda name, default="": self.headers.get(name, default)
		)
		self.header_patch.start()
		frappe.set_user(self.user.name)

	def tearDown(self) -> None:
		self.header_patch.stop()
		frappe.set_user("Administrator")
		for name in frappe.get_all(AUTHORIZATION_SOURCE, filters={"user": self.user.name}, pluck="name"):
			frappe.delete_doc(AUTHORIZATION_SOURCE, name, force=True, ignore_permissions=True)
		frappe.delete_doc("User", self.user.name, force=True, ignore_permissions=True)
		frappe.db.set_single_value("Flutter Utils Settings", "maximum_logged_in_devices", self.limit)
		frappe.set_user(self.old_user)
		frappe.local.login_manager = self.old_manager

	def test_authenticated_registration_rotation_and_logout(self) -> None:
		validate_api_key_secret(
			self.credentials["api_key"], self.credentials["api_secret"], AUTHORIZATION_SOURCE
		)
		first = register_push_device("old-token", "android", "example_mobile")
		self.assertEqual(frappe.get_doc(REGISTRATION_DOCTYPE, first["name"]).user, frappe.session.user)
		second = register_push_device("new-token", "android", "example_mobile")
		self.assertEqual(first["name"], second["name"])
		self.assertEqual(frappe.db.get_value(REGISTRATION_DOCTYPE, first["name"], "fcm_token"), "new-token")
		self.assertEqual(
			register_push_device("new-token", "android", "example_mobile")["name"], second["name"]
		)
		logout_current_device()
		self.assertFalse(frappe.db.get_value(REGISTRATION_DOCTYPE, second["name"], "push_enabled"))
		with self.assertRaises(frappe.AuthenticationError):
			register_push_device("new-token", "android", "example_mobile")

	def test_rejects_missing_source_guest_and_wrong_secret(self) -> None:
		for headers in (
			{},
			{"Authorization": self.headers["Authorization"]},
			{
				"Frappe-Authorization-Source": AUTHORIZATION_SOURCE,
				"Authorization": f"token {self.credentials['api_key']}:wrong",
			},
		):
			with patch(
				"frappe.get_request_header", side_effect=lambda name, default="": headers.get(name, default)
			):
				for action in (
					lambda: register_push_device("t", "web", "app"),
					lambda: unregister_push_device("t"),
				):
					with self.assertRaises(frappe.AuthenticationError):
						action()
		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			register_push_device("t", "web", "app")

	def test_invalid_input_and_device_scoped_unregister(self) -> None:
		for token, platform, app in (("", "web", "app"), ("t", "bad", "app"), ("t", "web", "bad app")):
			with self.assertRaises(frappe.ValidationError):
				register_push_device(token, platform, app)
		with self.assertRaises(frappe.ValidationError):
			unregister_push_device("")
		registration = register_push_device("private-token", "web", "app")
		self.headers["Authorization"] = f"token {self.second['api_key']}:{self.second['api_secret']}"
		unregister_push_device("private-token")
		self.assertTrue(frappe.db.get_value(REGISTRATION_DOCTYPE, registration["name"], "push_enabled"))

	def test_worker_filters_app_and_disabled_credentials(self) -> None:
		register_push_device("mobile-token", "android", "mobile")
		first_header = self.headers["Authorization"]
		self.headers["Authorization"] = f"token {self.second['api_key']}:{self.second['api_secret']}"
		register_push_device("web-token", "web", "admin")
		self.headers["Authorization"] = first_header
		settings = frappe._dict(enable_firebase_push=1)
		with (
			patch("flutter_utils.push_notifications.frappe.get_single", return_value=settings),
			patch("flutter_utils.firebase.get_firebase_app", return_value="configured-app"),
			patch(
				"firebase_admin.messaging.send_each_for_multicast",
				return_value=SimpleNamespace(responses=[SimpleNamespace(success=True)]),
			) as send,
		):
			send_push_notifications([self.user.name], "Title", "Body", app="mobile")
			self.assertEqual(send.call_args.args[0].tokens, ["mobile-token"])
			self.assertEqual(send.call_args.kwargs["app"], "configured-app")
			logout_current_device()
			send.reset_mock()
			send_push_notifications([self.user.name], "Title", "Body", app="mobile")
			send.assert_not_called()

	def test_enqueue_after_commit(self) -> None:
		with patch("frappe.enqueue") as enqueue:
			enqueue_push_notifications([self.user.name], "Title", "Body", "mobile")
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])

	def test_migration_preserves_latest_and_disabled_state_and_is_idempotent(self) -> None:
		from flutter_utils.patches.v1_0.merge_push_registration import execute

		first = frappe.db.get_value(AUTHORIZATION_SOURCE, {"api_key": self.credentials["api_key"]})
		second = frappe.db.get_value(AUTHORIZATION_SOURCE, {"api_key": self.second["api_key"]})
		frappe.db.set_value(AUTHORIZATION_SOURCE, second, "enabled", 0)
		legacy = "Flutter Push Registration"
		rows = [
			frappe._dict(
				device_credential=name,
				user=self.user.name,
				app="mobile",
				platform="android",
				token=token,
				active=1,
				last_seen_at="2026-09-22 12:00:00",
			)
			for name, token in ((first, "latest"), (first, "older"), (second, "disabled"))
		]
		get_all = frappe.get_all
		exists = frappe.db.exists
		with (
			patch("frappe.reload_doc"),
			patch(
				"frappe.get_all",
				side_effect=lambda doctype, **kwargs: (
					rows if doctype == legacy else get_all(doctype, **kwargs)
				),
			),
			patch(
				"frappe.db.exists",
				side_effect=lambda doctype, *args, **kwargs: (
					True if doctype == "DocType" and args == (legacy,) else exists(doctype, *args, **kwargs)
				),
			),
			patch("frappe.delete_doc") as retire,
		):
			execute()
			self.assertEqual(frappe.db.get_value(AUTHORIZATION_SOURCE, first, "fcm_token"), "latest")
			self.assertTrue(frappe.db.get_value(AUTHORIZATION_SOURCE, first, "push_enabled"))
			self.assertFalse(frappe.db.get_value(AUTHORIZATION_SOURCE, second, "push_enabled"))
			register_push_device("refreshed-after-migration", "web", "admin")
			execute()
			self.assertEqual(
				frappe.db.get_value(AUTHORIZATION_SOURCE, first, "fcm_token"), "refreshed-after-migration"
			)
			self.assertEqual(retire.call_count, 2)

	def test_disabling_credential_and_limit_eviction_clear_registrations(self) -> None:
		registration = register_push_device("evicted-token", "web", "mobile")
		frappe.db.set_single_value("Flutter Utils Settings", "maximum_logged_in_devices", 1)
		issue_device_api_credentials(self.user, "replacement-device")
		self.assertFalse(frappe.db.get_value(REGISTRATION_DOCTYPE, registration["name"], "push_enabled"))

	def test_token_reassignment_and_stale_unregister(self) -> None:
		first = register_push_device("shared-token", "web", "admin")
		self.headers["Authorization"] = f"token {self.second['api_key']}:{self.second['api_secret']}"
		second = register_push_device("shared-token", "android", "mobile")
		self.assertIsNone(frappe.db.get_value(REGISTRATION_DOCTYPE, first["name"], "fcm_token_hash"))
		self.assertFalse(frappe.db.get_value(REGISTRATION_DOCTYPE, first["name"], "push_enabled"))
		register_push_device("replacement-token", "android", "mobile")
		unregister_push_device("shared-token")
		self.assertTrue(frappe.db.get_value(REGISTRATION_DOCTYPE, second["name"], "push_enabled"))
		unregister_push_device("replacement-token")
		self.assertFalse(frappe.db.get_value(REGISTRATION_DOCTYPE, second["name"], "push_enabled"))
		self.assertTrue(frappe.db.get_value(REGISTRATION_DOCTYPE, second["name"], "enabled"))

	def test_one_app_per_credential_and_relogin_requires_registration(self) -> None:
		registration = register_push_device("first-token", "android", "mobile")
		register_push_device("second-token", "web", "admin")
		doc = frappe.get_doc(REGISTRATION_DOCTYPE, registration["name"])
		self.assertEqual((doc.app, doc.fcm_token), ("admin", "second-token"))
		logout_current_device()
		issue_device_api_credentials(self.user, "push-device-one")
		self.assertFalse(frappe.db.get_value(REGISTRATION_DOCTYPE, doc.name, "push_enabled"))

	def test_stale_worker_failure_preserves_refreshed_token(self) -> None:
		from firebase_admin import messaging

		registration = register_push_device("old-token", "android", "mobile")

		def fail_after_refresh(*args: object, **kwargs: object) -> SimpleNamespace:
			register_push_device("new-token", "android", "mobile")
			return SimpleNamespace(
				responses=[SimpleNamespace(success=False, exception=messaging.UnregisteredError("expired"))]
			)

		with (
			patch("frappe.get_single", return_value=frappe._dict(enable_firebase_push=1)),
			patch("flutter_utils.firebase.get_firebase_app", return_value="configured-app"),
			patch("firebase_admin.messaging.send_each_for_multicast", side_effect=fail_after_refresh) as send,
		):
			send_push_notifications([self.user.name], "Title", "Body", app="mobile")
			send.assert_called_once()
		self.assertTrue(frappe.db.get_value(REGISTRATION_DOCTYPE, registration["name"], "push_enabled"))

	def test_push_disabled_does_not_initialize_firebase(self) -> None:
		with (
			patch("frappe.get_single", return_value=frappe._dict(enable_firebase_push=0)),
			patch("flutter_utils.firebase.get_firebase_app") as initialize,
		):
			send_push_notifications([self.user.name], "Title", "Body", app="mobile")
		initialize.assert_not_called()

	def test_shared_firebase_uses_settings_without_auth_flag(self) -> None:
		from flutter_utils.firebase import get_firebase_app

		settings = Mock(firebase_project_id="test-project")
		service_account = {
			"project_id": "test-project",
			"client_email": "service@example.invalid",
			"private_key_id": "key-id",
		}
		with (
			patch("flutter_utils.firebase_auth.parse_service_account_json", return_value=service_account),
			patch("flutter_utils.firebase.get_app", side_effect=ValueError),
			patch("flutter_utils.firebase.credentials.Certificate", return_value="certificate"),
			patch("flutter_utils.firebase.initialize_app", return_value="firebase-app") as initialize,
		):
			self.assertEqual(get_firebase_app(settings), "firebase-app")
		settings.get_password.assert_called_once_with("firebase_service_account_json")
		self.assertEqual(initialize.call_args.args, ("certificate", {"projectId": "test-project"}))
		self.assertTrue(initialize.call_args.kwargs["name"].startswith("flutter-utils-"))
