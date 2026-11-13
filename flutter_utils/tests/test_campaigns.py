"""Database-independent campaign contracts. Outbound FCM is always mocked."""

from contextlib import ExitStack
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe

from flutter_utils.api import campaigns as api
from flutter_utils.campaigns import audience, schedule, worker


def campaign(**values: Any) -> frappe._dict:
	return frappe._dict(
		{
			"name": "campaign-1",
			"app": "mobile",
			"send_mode": "Recurring",
			"status": "Active",
			"frequency": "Monthly",
			"timezone": "UTC",
			"start_date": "2027-01-31",
			"send_time": "09:00:00",
			"end_date": None,
			"match_mode": "All",
			"audience_filters": [],
			"push_title": "Hello",
			"push_body": "Message",
			**values,
		}
	)


class CampaignTests(TestCase):
	def setUp(self) -> None:
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.stack.enter_context(
			patch.object(
				frappe,
				"throw",
				side_effect=lambda message: (_ for _ in ()).throw(frappe.ValidationError(message)),
			)
		)
		for module in (api, audience, schedule):
			self.stack.enter_context(patch.object(module, "_", side_effect=lambda message: message))
		self.stack.enter_context(patch.object(schedule, "get_system_timezone", return_value="UTC"))
		self.now = datetime(2027, 1, 1, 12)
		self.stack.enter_context(patch.object(worker, "now_datetime", return_value=self.now))

	def test_monthly_anchor_does_not_drift_after_february(self) -> None:
		doc = campaign()
		self.assertEqual(schedule.next_after(doc, datetime(2027, 1, 31, 9)), datetime(2027, 2, 28, 9))
		self.assertEqual(schedule.next_after(doc, datetime(2027, 2, 28, 9)), datetime(2027, 3, 31, 9))

	def test_recurrence_end_inclusive_and_downtime_skips_backlog(self) -> None:
		doc = campaign(frequency="Daily", start_date="2027-01-01", end_date="2027-01-10")
		self.assertEqual(schedule.next_after(doc, datetime(2027, 1, 9, 10)), datetime(2027, 1, 10, 9))
		self.assertIsNone(schedule.next_after(doc, datetime(2027, 1, 10, 9)))
		self.assertIsNone(schedule.next_after(campaign(send_mode="Scheduled"), self.now))

	def test_dst_gap_and_fold(self) -> None:
		gap = campaign(start_date="2027-03-14", send_time="02:30:00", timezone="America/New_York")
		self.assertEqual(schedule.occurrence(gap), datetime(2027, 3, 14, 7, 30))
		fold = campaign(start_date="2027-11-07", send_time="01:30:00", timezone="America/New_York")
		self.assertEqual(schedule.occurrence(fold), datetime(2027, 11, 7, 5, 30))

	def test_database_time_values_and_timezone_validation(self) -> None:
		doc = campaign(send_time=timedelta(hours=9))
		schedule.validate(doc)
		self.assertEqual(schedule.occurrence(doc), datetime(2027, 1, 31, 9))
		with self.assertRaises(frappe.ValidationError):
			schedule.validate(campaign(timezone="not/a/zone"))

	def _fields(self) -> list[frappe._dict]:
		return [
			frappe._dict(fieldname=name, label=name, fieldtype=kind, hidden=hidden, permlevel=level)
			for name, kind, hidden, level in [
				("gender", "Link", 0, 0),
				("language", "Link", 0, 0),
				("custom_age", "Int", 0, 0),
				("enabled", "Check", 0, 0),
				("api_key", "Data", 0, 0),
				("password", "Password", 0, 0),
				("hidden_value", "Data", 1, 0),
				("restricted", "Data", 0, 1),
				("custom_access_token", "Data", 0, 0),
			]
		]

	def test_field_metadata_excludes_sensitive_fields_and_includes_custom_fields(self) -> None:
		with patch.object(frappe, "get_meta", return_value=SimpleNamespace(fields=self._fields())):
			self.assertEqual(set(audience.fields()), {"gender", "language", "custom_age", "enabled"})

	def test_any_filters_cannot_bypass_enabled_user_constraint(self) -> None:
		rows = [frappe._dict(user_field="language", operator="in", value="en, ar")]
		with patch.object(frappe, "get_meta", return_value=SimpleNamespace(fields=self._fields())):
			query = audience.query(campaign(match_mode="Any", audience_filters=rows))
		self.assertIn(["User", "enabled", "=", 1], query["filters"])
		self.assertEqual(query["or_filters"], [["User", "language", "in", ["en", "ar"]]])

	def test_invalid_fields_operators_and_values_are_rejected(self) -> None:
		with patch.object(frappe, "get_meta", return_value=SimpleNamespace(fields=self._fields())):
			for field, operator, value in [
				("api_key", "=", "x"),
				("roles.role", "=", "x"),
				("language", "contains", "a"),
				("custom_age", ">", "nan"),
				("language", "in", ", ,"),
			]:
				with self.subTest(field=field, operator=operator), self.assertRaises(frappe.ValidationError):
					audience.query(
						campaign(
							audience_filters=[frappe._dict(user_field=field, operator=operator, value=value)]
						)
					)

	def test_numeric_zero_is_a_valid_filter(self) -> None:
		with patch.object(frappe, "get_meta", return_value=SimpleNamespace(fields=self._fields())):
			query = audience.query(
				campaign(audience_filters=[frappe._dict(user_field="enabled", operator="=", value=0)])
			)
		self.assertEqual(query["filters"][-1][-1], 0)

	def test_all_endpoints_require_manager_before_reading_records(self) -> None:
		with (
			patch.object(frappe, "only_for", side_effect=frappe.PermissionError),
			patch.object(frappe, "get_doc") as read,
		):
			for function, args in [
				(api.get_user_fields, ()),
				(api.preview, ("campaign-1",)),
				(api.action, ("campaign-1", "start")),
			]:
				with self.assertRaises(frappe.PermissionError):
					function(*args)
			read.assert_not_called()

	def test_quota_retry_is_bounded_and_transport_errors_are_not_retried(self) -> None:
		from firebase_admin import messaging

		with patch.object(messaging, "send", side_effect=messaging.QuotaExceededError("quota")):
			self.assertEqual(worker.send_device(Mock(), "token", campaign(), "d1", 1)["status"], "Retry")
			self.assertEqual(worker.send_device(Mock(), "token", campaign(), "d1", 5)["status"], "Failed")
		with patch.object(messaging, "send", side_effect=TimeoutError), patch.object(frappe, "log_error"):
			self.assertEqual(worker.send_device(Mock(), "token", campaign(), "d1", 1)["status"], "Unknown")

	def test_app_user_token_and_optout_are_rechecked(self) -> None:
		delivery = frappe._dict(recipient="alice", token_hash="hash")
		device = frappe._dict(
			user="alice", app="mobile", fcm_token="token", fcm_token_hash="hash", enabled=1, push_enabled=1
		)
		self.assertTrue(worker.eligible_device(device, delivery, campaign()))
		for key, value in [
			("user", "bob"),
			("app", "other"),
			("fcm_token_hash", "new"),
			("push_enabled", 0),
			("enabled", 0),
		]:
			changed = frappe._dict({**device, key: value})
			self.assertFalse(worker.eligible_device(changed, delivery, campaign()))

	def _delivery_environment(
		self, status: str = "Pending", campaign_status: str = "Active"
	) -> tuple[Mock, frappe._dict]:
		delivery = frappe._dict(
			name="d1",
			run="r1",
			recipient="alice",
			credential="device1",
			token_hash="hash",
			attempts=0,
			next_attempt_at=None,
			status=status,
		)
		doc = campaign(status=campaign_status)
		device = frappe._dict(
			user="alice", app="mobile", enabled=1, push_enabled=1, fcm_token="token", fcm_token_hash="hash"
		)
		db = Mock()

		def get_value(doctype: str, name: str, field: Any, **kwargs: Any) -> Any:
			if kwargs.get("for_update"):
				return name
			if doctype == worker.DELIVERY:
				return "r1"
			if doctype == worker.RUN:
				return "campaign-1"
			if doctype == "User":
				return 1
			return device

		db.get_value.side_effect = get_value
		self.stack.enter_context(patch.object(frappe, "db", db, create=True))
		self.stack.enter_context(
			patch.object(
				frappe, "get_doc", side_effect=lambda dt, name: delivery if dt == worker.DELIVERY else doc
			)
		)
		self.stack.enter_context(
			patch.object(frappe, "get_single", return_value=frappe._dict(enable_firebase_push=1))
		)
		self.stack.enter_context(patch("flutter_utils.firebase.get_firebase_app", return_value=Mock()))
		return db, delivery

	def test_send_marker_commits_before_fcm_and_duplicate_worker_does_not_send(self) -> None:
		db, delivery = self._delivery_environment()
		events = []
		db.commit.side_effect = lambda: events.append("commit")

		def update(dt: str, name: str, values: dict[str, Any]) -> None:
			delivery.update(values)
			events.append(values["status"])

		def send(*args: Any) -> dict[str, str]:
			self.assertEqual(events, ["Sending", "commit"])
			events.append("fcm")
			return {"status": "Accepted"}

		with (
			patch.object(worker, "_update", side_effect=update),
			patch.object(worker, "send_device", side_effect=send) as outbound,
		):
			worker.deliver("d1")
			worker.deliver("d1")
			outbound.assert_called_once()
		self.assertEqual(events, ["Sending", "commit", "fcm", "Accepted"])

	def test_pause_and_cancel_do_not_send(self) -> None:
		for status in ("Paused", "Cancelled"):
			with self.subTest(status=status):
				self._delivery_environment(campaign_status=status)
				with patch.object(worker, "_update") as update, patch.object(worker, "send_device") as send:
					worker.deliver("d1")
					send.assert_not_called()
					if status == "Cancelled":
						self.assertEqual(update.call_args.args[2]["status"], "Skipped")

	def test_start_persists_before_enqueue_and_rejects_bad_action(self) -> None:
		doc = Mock()
		doc.status = "Draft"
		doc.send_mode = "Now"
		doc.next_run_at = None
		with (
			patch.object(api, "require_manager"),
			patch.object(frappe, "db", Mock(), create=True),
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "get_single", return_value=frappe._dict(enable_firebase_push=1)),
			patch.object(api, "now_datetime", return_value=self.now),
			patch.object(frappe, "enqueue") as enqueue,
		):
			enqueue.side_effect = lambda *args, **kwargs: doc.save.assert_called_once()
			result = api.action("c1", "start")
			self.assertEqual(result["status"], "Active")
			self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
			with self.assertRaises(frappe.ValidationError):
				api.action("c1", "invented")

	def test_preview_reports_users_devices_and_bounded_sample(self) -> None:
		doc = Mock(app="mobile")
		with (
			patch.object(api, "require_manager"),
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(api, "matching_users", return_value=["alice", "bob"]),
			patch.object(
				api, "devices", return_value=[frappe._dict(user="alice"), frappe._dict(user="alice")]
			),
			patch.object(frappe, "get_all", return_value=[{"name": "alice", "full_name": "Alice"}]),
		):
			result = api.preview("c1")
		self.assertEqual(
			(result["matched_users"], result["eligible_users"], result["eligible_devices"]), (2, 1, 2)
		)
