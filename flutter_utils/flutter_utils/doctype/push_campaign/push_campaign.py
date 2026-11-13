import re

import frappe
from frappe import _
from frappe.model.document import Document

from flutter_utils.campaigns import audience, schedule


class PushCampaign(Document):
	def validate(self) -> None:
		old = self.get_doc_before_save()
		if not self.flags.campaign_action:
			if self.is_new() and (self.status != "Draft" or self.next_run_at):
				frappe.throw(_("New campaigns must be drafts."))
			if old and (self.status != old.status or self.next_run_at != old.next_run_at):
				frappe.throw(_("Use campaign actions to change status."))
			if old and old.status != "Draft":
				frappe.throw(
					_("Started campaigns are immutable. Duplicate this campaign to change its content.")
				)
		if self.flags.campaign_action and old:
			return
		if not re.fullmatch(r"[A-Za-z0-9_.-]{1,140}", self.app or ""):
			frappe.throw(_("Enter a valid app identifier."))
		if not (self.push_title or "").strip() or len(self.push_title.encode()) > 200:
			frappe.throw(_("Push title must contain 1-200 UTF-8 bytes."))
		if not (self.push_body or "").strip() or len(self.push_body.encode()) > 2000:
			frappe.throw(_("Push message must contain 1-2000 UTF-8 bytes."))
		audience.query(self)
		schedule.validate(self)

	def on_trash(self) -> None:
		if self.status != "Draft":
			frappe.throw(_("Campaign history cannot be deleted."))
