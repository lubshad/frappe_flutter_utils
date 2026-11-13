"""Wall-clock recurrence anchored to the first date, stored in site time."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe
from dateutil.relativedelta import relativedelta
from frappe import _
from frappe.utils import get_datetime, get_system_timezone, get_time, getdate


def validate(campaign: Any) -> None:
	if campaign.send_mode not in {"Now", "Scheduled", "Recurring"}:
		frappe.throw(_("Choose a valid send mode."))
	try:
		ZoneInfo(campaign.timezone or "")
	except ZoneInfoNotFoundError, ValueError:
		frappe.throw(_("Enter a valid IANA timezone, for example Asia/Kolkata."))
	if campaign.send_mode == "Now":
		return
	if not campaign.start_date or campaign.send_time in (None, ""):
		frappe.throw(_("Start date and send time are required."))
	try:
		get_time(campaign.send_time)
	except ValueError, TypeError, OverflowError:
		frappe.throw(_("Enter a valid send time."))
	if campaign.send_mode == "Recurring" and campaign.frequency not in {"Daily", "Weekly", "Monthly"}:
		frappe.throw(_("Choose a recurrence frequency."))
	if campaign.end_date and getdate(campaign.end_date) < getdate(campaign.start_date):
		frappe.throw(_("End date cannot precede start date."))


def occurrence(campaign: Any, index: int = 0) -> datetime:
	start = getdate(campaign.start_date)
	if campaign.frequency == "Monthly":
		day = start + relativedelta(months=index)
	else:
		day = start + timedelta(days=index * (7 if campaign.frequency == "Weekly" else 1))
	wall = datetime.combine(day, get_time(campaign.send_time))
	zone = ZoneInfo(campaign.timezone)
	# Ambiguous times use the first occurrence; nonexistent times move forward across the DST gap.
	local = wall.replace(tzinfo=zone, fold=0).astimezone(ZoneInfo("UTC")).astimezone(zone)
	return local.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)


def next_after(campaign: Any, after: datetime) -> datetime | None:
	if campaign.send_mode != "Recurring":
		return None
	after = get_datetime(after)
	local = after.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(ZoneInfo(campaign.timezone))
	start = getdate(campaign.start_date)
	if campaign.frequency == "Monthly":
		index = max(0, (local.year - start.year) * 12 + local.month - start.month)
	else:
		index = max(0, (local.date() - start).days // (7 if campaign.frequency == "Weekly" else 1))
	while True:
		candidate = occurrence(campaign, index)
		candidate_day = (
			candidate.replace(tzinfo=ZoneInfo(get_system_timezone()))
			.astimezone(ZoneInfo(campaign.timezone))
			.date()
		)
		if campaign.end_date and candidate_day > getdate(campaign.end_date):
			return None
		if candidate > after:
			return candidate
		index += 1
