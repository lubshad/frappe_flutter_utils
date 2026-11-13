from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from flutter_utils.campaigns import audience, schedule

MAX_AUDIENCE = 50000


def require_manager() -> None:
	frappe.only_for("System Manager")
	frappe.has_permission("User", "read", throw=True)


@frappe.whitelist()
def get_user_fields() -> list[dict[str, Any]]:
	require_manager()
	return [
		{
			"fieldname": name,
			"label": field.label,
			"fieldtype": field.fieldtype,
			"options": field.options,
			"operators": audience.operators(field),
		}
		for name, field in audience.fields().items()
	]


def matching_users(campaign: Any) -> list[str]:
	users = frappe.get_all(
		"User", **audience.query(campaign), pluck="name", order_by="name", limit_page_length=MAX_AUDIENCE + 1
	)
	if len(users) > MAX_AUDIENCE:
		frappe.throw(_("Audience exceeds 50,000 users. Narrow the audience conditions."))
	return users


def devices(users: list[str], app: str) -> list[Any]:
	result = []
	for offset in range(0, len(users), 500):
		result.extend(
			frappe.get_all(
				"Flutter Device Credential",
				filters={
					"user": ["in", users[offset : offset + 500]],
					"app": app,
					"enabled": 1,
					"push_enabled": 1,
					"fcm_token": ["is", "set"],
				},
				fields=["name", "user", "fcm_token_hash"],
			)
		)
	return result


@frappe.whitelist()
def preview(name: str) -> dict[str, Any]:
	require_manager()
	campaign = frappe.get_doc("Push Campaign", name)
	campaign.check_permission("read")
	users = matching_users(campaign)
	registrations = devices(users, campaign.app)
	sample = (
		frappe.get_all(
			"User", filters={"name": ["in", users[:20]]}, fields=["name", "full_name"], order_by="name"
		)
		if users
		else []
	)
	return {
		"matched_users": len(users),
		"eligible_users": len({row.user for row in registrations}),
		"eligible_devices": len(registrations),
		"sample": sample,
	}


@frappe.whitelist(methods=["POST"])
def action(name: str, action: str) -> dict[str, Any]:
	require_manager()
	frappe.db.get_value("Push Campaign", name, "name", for_update=True)
	campaign = frappe.get_doc("Push Campaign", name)
	campaign.check_permission("write")
	transitions = {
		"start": ("Draft", "Active"),
		"pause": ("Active", "Paused"),
		"resume": ("Paused", "Active"),
	}
	if action == "cancel":
		if campaign.status not in {"Draft", "Active", "Paused"}:
			frappe.throw(_("This campaign can no longer be cancelled."))
		campaign.status, campaign.next_run_at = "Cancelled", None
	elif action in transitions:
		before, after = transitions[action]
		if campaign.status != before:
			frappe.throw(_("Campaign status changed. Reload and try again."))
		if action in {"start", "resume"}:
			if not frappe.get_single("Flutter Utils Settings").get("enable_firebase_push"):
				frappe.throw(_("Enable Firebase Push in Flutter Utils Settings first."))
		if action == "start":
			campaign.validate()
			due = now_datetime() if campaign.send_mode == "Now" else schedule.occurrence(campaign)
			if campaign.send_mode != "Now" and due < now_datetime():
				frappe.throw(_("Choose a future start date and time."))
			campaign.next_run_at = due
		campaign.status = after
	else:
		frappe.throw(_("Unknown campaign action."))
	campaign.flags.campaign_action = True
	campaign.save()
	frappe.enqueue("flutter_utils.campaigns.worker.dispatch", queue="long", enqueue_after_commit=True)
	return {"status": campaign.status, "next_run_at": campaign.next_run_at}
