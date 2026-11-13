"""Run against an explicitly selected migrated site; all fixture writes roll back.

No real FCM calls, queue jobs, or commits are allowed inside these tests.
"""

import uuid
from contextlib import ExitStack
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime

from flutter_utils.api import campaigns as api
from flutter_utils.campaigns import worker


class CampaignIntegrationTests(TestCase):
	def setUp(self) -> None:
		if not getattr(frappe.local, "site", None):
			self.skipTest("Connect an explicitly selected migrated site first.")
		self.stack = ExitStack()
		self.addCleanup(self.stack.close)
		self.addCleanup(frappe.db.rollback)
		self.original_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self.original_user))
		frappe.set_user("Administrator")
		self.stack.enter_context(
			patch.object(frappe.db, "commit", side_effect=AssertionError("Unexpected commit"))
		)
		self.stack.enter_context(patch.object(frappe, "enqueue"))
		self.stack.enter_context(patch.object(frappe, "publish_realtime"))
		self.stack.enter_context(
			patch.object(frappe, "get_single", return_value=frappe._dict(enable_firebase_push=1))
		)
		self.stack.enter_context(patch("flutter_utils.firebase.get_firebase_app", return_value=object()))

	def test_native_campaign_lifecycle_and_partial_retry(self) -> None:
		users = frappe.get_all(
			"User",
			filters={"enabled": 1, "name": ["not in", ["Administrator", "Guest"]]},
			fields=["name", "email"],
			limit_page_length=1,
		)
		if not users:
			self.skipTest("Requires one existing enabled user.")
		user = users[0]
		app = f"campaign-test-{uuid.uuid4().hex}"
		campaign = frappe.get_doc(
			{
				"doctype": "Push Campaign",
				"campaign_name": app,
				"app": app,
				"push_title": "Test",
				"push_body": "Never sent",
				"send_mode": "Now",
				"timezone": "UTC",
				"match_mode": "All",
				"audience_filters": [{"user_field": "email", "operator": "=", "value": user.email}],
			}
		).insert()
		for _index in range(2):
			key = uuid.uuid4().hex
			frappe.get_doc(
				{
					"doctype": "Flutter Device Credential",
					"user": user.name,
					"enabled": 1,
					"last_login_at": now_datetime(),
					"device_id_hash": key,
					"device_key": key,
					"api_key": key,
					"api_secret": key,
					"app": app,
					"platform": "android",
					"push_enabled": 1,
					"fcm_token": f"fake-{key}",
					"fcm_token_hash": key,
				}
			).insert(ignore_permissions=True)
		preview = api.preview(campaign.name)
		self.assertEqual(preview["eligible_devices"], 2)
		self.assertEqual(preview["eligible_users"], 1)
		api.action(campaign.name, "start")
		worker.claim_run(campaign.name)
		worker.claim_run(campaign.name)
		runs = frappe.get_all("Push Campaign Run", filters={"campaign": campaign.name}, pluck="name")
		self.assertEqual(len(runs), 1)
		worker.prepare_run(runs[0])
		worker.prepare_run(runs[0])
		deliveries = frappe.get_all("Push Campaign Delivery", filters={"run": runs[0]}, pluck="name")
		self.assertEqual(len(deliveries), 2)
		api.action(campaign.name, "pause")
		worker.deliver(deliveries[0])
		self.assertEqual(frappe.db.get_value("Push Campaign Delivery", deliveries[0], "attempts"), 0)
		api.action(campaign.name, "resume")
		frappe.db.set_value("Push Campaign Delivery", deliveries[0], "next_attempt_at", None)
		with (
			patch.object(frappe.db, "commit"),
			patch.object(
				worker,
				"send_device",
				side_effect=[
					{"status": "Accepted"},
					worker.retry_result(1, "QuotaExceededError"),
					{"status": "Accepted"},
				],
			) as send,
		):
			worker.deliver(deliveries[0])
			worker.deliver(deliveries[1])
			worker.deliver(deliveries[0])
			self.assertEqual(send.call_count, 2)
			frappe.db.set_value("Push Campaign Delivery", deliveries[1], "next_attempt_at", None)
			worker.deliver(deliveries[1])
			self.assertEqual(send.call_count, 3)
		worker.finish_run(runs[0])
		worker.finish_campaign(campaign.name)
		run = frappe.get_doc("Push Campaign Run", runs[0])
		self.assertEqual((run.status, run.accepted), ("Completed", 2))
		self.assertEqual(frappe.db.get_value("Push Campaign", campaign.name, "status"), "Completed")
		with self.assertRaises(frappe.ValidationError):
			api.action(campaign.name, "resume")
		campaign.reload()
		campaign.push_title = "Cannot change sent content"
		with self.assertRaises(frappe.ValidationError):
			campaign.save()
