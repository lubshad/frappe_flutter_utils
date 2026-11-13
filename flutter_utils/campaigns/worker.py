"""Durable campaign outbox. Ambiguous sends are never retried automatically."""

import hashlib
from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import get_datetime, now_datetime

from flutter_utils.api.campaigns import devices, matching_users
from flutter_utils.campaigns import schedule

CAMPAIGN = "Push Campaign"
RUN = "Push Campaign Run"
DELIVERY = "Push Campaign Delivery"
MAX_ATTEMPTS = 5


def _key(value: str) -> str:
	return hashlib.sha256(value.encode()).hexdigest()


def _update(doctype: str, name: str, values: dict[str, Any]) -> None:
	doc = frappe.get_doc(doctype, name)
	doc.update(values)
	if doctype == CAMPAIGN:
		doc.flags.campaign_action = True
	doc.save(ignore_permissions=True)


def enqueue_due() -> None:
	frappe.enqueue("flutter_utils.campaigns.worker.dispatch", queue="long", enqueue_after_commit=True)


def dispatch() -> None:
	"""Bounded passes. Row locks and unique keys serialize overlapping workers."""
	if not frappe.db.exists("DocType", CAMPAIGN):
		return
	for name in frappe.get_all(
		CAMPAIGN,
		filters={"status": "Active", "next_run_at": ["<=", now_datetime()]},
		order_by="next_run_at",
		limit_page_length=20,
		pluck="name",
	):
		_isolated(claim_run, name)
	for name in frappe.get_all(
		RUN, filters={"status": "Pending"}, order_by="modified", limit_page_length=20, pluck="name"
	):
		_isolated(prepare_run, name)
	# A process may die after FCM accepted a request. Do not resend this uncertain outcome.
	for name in frappe.get_all(
		DELIVERY,
		filters={"status": "Sending", "modified": ["<", now_datetime() - timedelta(minutes=15)]},
		limit_page_length=500,
		pluck="name",
	):
		frappe.db.get_value(DELIVERY, name, "name", for_update=True)
		doc = frappe.get_doc(DELIVERY, name)
		if doc.status == "Sending" and get_datetime(doc.modified) < now_datetime() - timedelta(minutes=15):
			_update(DELIVERY, name, {"status": "Unknown", "last_error": "WorkerInterrupted"})
		frappe.db.commit()
	for name in frappe.get_all(
		DELIVERY,
		filters={"status": ["in", ["Pending", "Retry"]]},
		or_filters=[["next_attempt_at", "is", "not set"], ["next_attempt_at", "<=", now_datetime()]],
		order_by="modified",
		limit_page_length=100,
		pluck="name",
	):
		_isolated(deliver, name)
	for name in frappe.get_all(
		RUN, filters={"status": "Ready"}, order_by="modified", limit_page_length=100, pluck="name"
	):
		_isolated(finish_run, name)
	for name in frappe.get_all(
		CAMPAIGN,
		filters={"status": "Active", "next_run_at": ["is", "not set"]},
		limit_page_length=100,
		pluck="name",
	):
		_isolated(finish_campaign, name)


def _isolated(function: Any, name: str) -> None:
	try:
		function(name)
		frappe.db.commit()
	except Exception as exc:
		frappe.db.rollback()
		frappe.log_error(
			title="Push campaign processing failed", message=f"{function.__name__}: {type(exc).__name__}"
		)
		if function == prepare_run:
			_update(RUN, name, {"status": "Failed", "last_error": "AudiencePreparationFailed"})
			frappe.db.commit()


def claim_run(name: str) -> None:
	frappe.db.get_value(CAMPAIGN, name, "name", for_update=True)
	campaign = frappe.get_doc(CAMPAIGN, name)
	if (
		campaign.status != "Active"
		or not campaign.next_run_at
		or get_datetime(campaign.next_run_at) > now_datetime()
	):
		return
	due = get_datetime(campaign.next_run_at)
	key = _key(f"{name}:{due.isoformat()}")
	if not frappe.db.exists(RUN, {"run_key": key}):
		frappe.get_doc(
			{"doctype": RUN, "campaign": name, "run_key": key, "scheduled_at": due, "status": "Pending"}
		).insert(ignore_permissions=True)
	# One catch-up run after downtime, then the next future wall-clock occurrence.
	_update(CAMPAIGN, name, {"next_run_at": schedule.next_after(campaign, now_datetime())})


def prepare_run(name: str) -> None:
	# Always lock campaign before run/delivery, matching action and delivery lock order.
	campaign_name = frappe.db.get_value(RUN, name, "campaign")
	frappe.db.get_value(CAMPAIGN, campaign_name, "name", for_update=True)
	frappe.db.get_value(RUN, name, "name", for_update=True)
	run = frappe.get_doc(RUN, name)
	if run.status != "Pending":
		return
	campaign = frappe.get_doc(CAMPAIGN, run.campaign)
	if campaign.status == "Paused":
		_update(RUN, name, {"status": "Pending"})
		return
	if campaign.status == "Cancelled":
		_update(RUN, name, {"status": "Cancelled"})
		return
	users = matching_users(campaign)
	registrations = devices(users, campaign.app)
	for device in registrations:
		frappe.get_doc(
			{
				"doctype": DELIVERY,
				"run": name,
				"recipient": device.user,
				"credential": device.name,
				"token_hash": device.fcm_token_hash,
				"delivery_key": _key(f"{name}:{device.name}"),
				"status": "Pending",
			}
		).insert(ignore_permissions=True)
	_update(RUN, name, {"status": "Ready", "recipient_count": len(users), "device_count": len(registrations)})


def deliver(name: str) -> None:
	run_name = frappe.db.get_value(DELIVERY, name, "run")
	campaign_name = frappe.db.get_value(RUN, run_name, "campaign")
	frappe.db.get_value(CAMPAIGN, campaign_name, "name", for_update=True)
	frappe.db.get_value(DELIVERY, name, "name", for_update=True)
	delivery = frappe.get_doc(DELIVERY, name)
	campaign = frappe.get_doc(CAMPAIGN, campaign_name)
	if delivery.status not in {"Pending", "Retry"}:
		return
	if delivery.next_attempt_at and get_datetime(delivery.next_attempt_at) > now_datetime():
		return
	if campaign.status == "Paused":
		# Move to the back of the bounded scan without consuming an attempt.
		_update(DELIVERY, name, {"next_attempt_at": now_datetime() + timedelta(minutes=1)})
		return
	if campaign.status == "Cancelled":
		_update(DELIVERY, name, {"status": "Skipped", "last_error": "CampaignCancelled"})
		return
	device = frappe.db.get_value(
		"Flutter Device Credential",
		delivery.credential,
		["user", "app", "enabled", "push_enabled", "fcm_token", "fcm_token_hash"],
		as_dict=True,
	)
	if not eligible_device(device, delivery, campaign) or not frappe.db.get_value(
		"User", delivery.recipient, "enabled"
	):
		_update(DELIVERY, name, {"status": "Skipped", "last_error": "DeviceNoLongerEligible"})
		return
	settings = frappe.get_single("Flutter Utils Settings")
	if not settings.get("enable_firebase_push"):
		_update(DELIVERY, name, {"status": "Skipped", "last_error": "PushDisabled"})
		return
	# Initialize credentials before claiming a send; failure here cannot have reached FCM.
	try:
		from flutter_utils.firebase import get_firebase_app

		firebase_app = get_firebase_app(settings)
	except Exception as exc:
		result = retry_result(delivery.attempts + 1, type(exc).__name__)
		_update(DELIVERY, name, {**result, "attempts": delivery.attempts + 1})
		return
	attempt = delivery.attempts + 1
	_update(DELIVERY, name, {"status": "Sending", "attempts": attempt, "last_error": None})
	frappe.db.commit()  # Persist the no-blind-resend marker before contacting FCM.
	result = send_device(firebase_app, device.fcm_token, campaign, name, attempt)
	frappe.db.get_value(DELIVERY, name, "name", for_update=True)
	_update(DELIVERY, name, result)
	if result.get("last_error") == "UnregisteredError":
		frappe.db.set_value(
			"Flutter Device Credential",
			{
				"name": delivery.credential,
				"fcm_token_hash": delivery.token_hash,
			},
			"push_enabled",
			0,
			update_modified=False,
		)


def eligible_device(device: Any, delivery: Any, campaign: Any) -> bool:
	return bool(
		device
		and device.enabled
		and device.push_enabled
		and device.fcm_token
		and device.user == delivery.recipient
		and device.app == campaign.app
		and device.fcm_token_hash == delivery.token_hash
	)


def retry_result(attempt: int, error: str) -> dict[str, Any]:
	return {
		"status": "Retry" if attempt < MAX_ATTEMPTS else "Failed",
		"last_error": error,
		"next_attempt_at": now_datetime() + timedelta(minutes=2**attempt) if attempt < MAX_ATTEMPTS else None,
	}


def send_device(
	firebase_app: Any, token: str, campaign: Any, delivery_id: str, attempt: int
) -> dict[str, Any]:
	from firebase_admin import messaging

	from flutter_utils.push_notifications import ANDROID_CHANNEL_ID, ANDROID_ICON

	try:
		messaging.send(
			messaging.Message(
				token=token,
				notification=messaging.Notification(title=campaign.push_title, body=campaign.push_body),
				data={"type": "campaign", "campaign": campaign.name, "delivery_id": delivery_id},
				android=messaging.AndroidConfig(
					priority="high",
					notification=messaging.AndroidNotification(
						channel_id=ANDROID_CHANNEL_ID, icon=ANDROID_ICON, default_sound=True
					),
				),
				apns=messaging.APNSConfig(payload=messaging.APNSPayload(aps=messaging.Aps(sound="default"))),
			),
			app=firebase_app,
		)
		return {"status": "Accepted", "last_error": None, "next_attempt_at": None}
	except Exception as exc:
		# Only explicit provider rejection is retryable. Transport failure may follow acceptance.
		code = type(exc).__name__
		if code == "QuotaExceededError":
			return retry_result(attempt, code)
		if code in {
			"UnregisteredError",
			"SenderIdMismatchError",
			"InvalidArgumentError",
			"ThirdPartyAuthError",
		}:
			return {"status": "Failed", "last_error": code}
		frappe.log_error(title="Push campaign delivery uncertain", message=code)
		return {"status": "Unknown", "last_error": code}


def finish_run(name: str) -> None:
	campaign_name = frappe.db.get_value(RUN, name, "campaign")
	frappe.db.get_value(CAMPAIGN, campaign_name, "name", for_update=True)
	frappe.db.get_value(RUN, name, "name", for_update=True)
	run = frappe.get_doc(RUN, name)
	if run.status != "Ready":
		return
	counts = frappe.get_all(
		DELIVERY,
		filters={"run": name},
		fields=["status", {"COUNT": "name", "as": "total"}],
		group_by="status",
	)
	totals = {row.status: row.total for row in counts}
	values = {key.lower(): totals.get(key, 0) for key in ("Accepted", "Failed", "Skipped", "Unknown")}
	if not any(totals.get(key) for key in ("Pending", "Retry", "Sending")):
		values["status"] = "Completed"
	_update(RUN, name, values)


def finish_campaign(name: str) -> None:
	frappe.db.get_value(CAMPAIGN, name, "name", for_update=True)
	campaign = frappe.get_doc(CAMPAIGN, name)
	if campaign.status == "Active" and not campaign.next_run_at and frappe.db.exists(RUN, {"campaign": name}):
		if not frappe.db.exists(RUN, {"campaign": name, "status": ["in", ["Pending", "Ready"]]}):
			_update(CAMPAIGN, name, {"status": "Completed"})
