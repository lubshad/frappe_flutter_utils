# Copyright (c) 2026, CoreAxis Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class FlutterUtilsSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		email_otp_body_template: DF.TextEditor | None
		email_otp_subject_template: DF.Data | None
		enable_email_otp: DF.Check
		enable_firebase_auth: DF.Check
		enable_firebase_google_auth: DF.Check
		enable_firebase_phone_auth: DF.Check
		enable_mobile_otp: DF.Check
		default_banner_slideshow: DF.Link | None
		firebase_auto_create_users: DF.Check
		firebase_check_revoked_tokens: DF.Check
		firebase_project_id: DF.Data | None
		firebase_service_account_json: DF.Password | None
		ultramsg_base_url: DF.Data | None
		ultramsg_instance_id: DF.Data | None
		ultramsg_token: DF.Password | None
		otp_length: DF.Literal["4", "6"]
		otp_resend_cooldown_seconds: DF.Int
		otp_ttl_seconds: DF.Int
		otp_default_region: DF.Link | None
		sms_otp_body_template: DF.SmallText | None
		sms_gateway: DF.Literal["", "Twilio", "UltraMsg"] | None
		test_mode: DF.Check
		twilio_account_sid: DF.Data | None
		twilio_auth_token: DF.Password | None
		twilio_from_number: DF.Data | None
	# end: auto-generated types

	def validate(self):
		if self.otp_default_region:
			self.otp_default_region = self.otp_default_region.strip().upper()
		if not self.otp_ttl_seconds or self.otp_ttl_seconds < 30:
			frappe.throw(_("OTP TTL must be at least 30 seconds."))

		if not self.enable_email_otp and not self.enable_mobile_otp and not self.enable_firebase_auth:
			frappe.throw(_("Enable at least one authentication provider."))

		self._validate_firebase_settings()

		if not self.enable_mobile_otp or self.test_mode:
			return

		if self.sms_gateway not in {"Twilio", "UltraMsg"}:
			frappe.throw(_("Select a supported SMS gateway before enabling Mobile OTP."))

		required_fields = {}
		if self.sms_gateway == "Twilio":
			required_fields = {
				"twilio_account_sid": _("Twilio Account SID"),
				"twilio_auth_token": _("Twilio Auth Token"),
				"twilio_from_number": _("Twilio From Number"),
			}
		elif self.sms_gateway == "UltraMsg":
			required_fields = {
				"ultramsg_instance_id": _("UltraMsg Instance ID"),
				"ultramsg_token": _("UltraMsg Token"),
			}

		for fieldname, label in required_fields.items():
			value = (
				self.get_password(fieldname)
				if fieldname in {"twilio_auth_token", "ultramsg_token"}
				else self.get(fieldname)
			)
			if not value:
				frappe.throw(_("{0} is required when Mobile OTP is enabled.").format(label))

	def _validate_firebase_settings(self) -> None:
		if not self.enable_firebase_auth:
			return

		if not self.enable_firebase_phone_auth and not self.enable_firebase_google_auth:
			frappe.throw(_("Enable Firebase Phone Auth or Firebase Google Auth."))

		if not self.firebase_project_id or not self.firebase_project_id.strip():
			frappe.throw(_("Firebase Project ID is required."))
		self.firebase_project_id = self.firebase_project_id.strip()

		from flutter_utils.firebase_auth import parse_service_account_json

		service_account = parse_service_account_json(self.get_password("firebase_service_account_json"))
		if service_account.get("project_id") != self.firebase_project_id:
			frappe.throw(_("Firebase Project ID must match the service account project_id."))

	@frappe.whitelist()
	def send_test_message(self, channel: str, recipient: str):
		from flutter_utils.api.auth import send_configured_test_message

		return send_configured_test_message(self.name, channel=channel, recipient=recipient)

	@frappe.whitelist()
	def test_firebase_connection(self) -> dict:
		from flutter_utils.firebase_auth import test_firebase_connection

		return test_firebase_connection()
