import json

import frappe
from frappe import _
from werkzeug.wrappers import Response


def _build_message_from_exception(e):
	"""Fallback: build a human-readable message from the exception itself."""
	if isinstance(e, frappe.OutgoingEmailError):
		return _("OTP email delivery is not configured. Please contact support.")
	if isinstance(e, frappe.ValidationError):
		parts = str(e).split("ValidationError:")
		return parts[-1].lstrip(": ").strip() if len(parts) > 1 else str(e)
	if isinstance(e, frappe.PermissionError):
		return _("You do not have enough permissions to complete this action.")
	if isinstance(e, frappe.DoesNotExistError):
		return _("The resource you are looking for was not found.")
	if isinstance(e, frappe.AuthenticationError):
		return _("Authentication failed. Please check your credentials.")
	if isinstance(e, frappe.SessionStopped):
		return _("The session has stopped. Please login again.")
	if frappe.conf.developer_mode:
		parts = str(e).split(": ", 1)
		return parts[1] if len(parts) > 1 else parts[0]
	return _("Something went wrong. Please try again later.")


def _resolve_error_code(e):
	if isinstance(e, frappe.OutgoingEmailError):
		return "outgoing_email_not_configured"
	if isinstance(e, frappe.ValidationError):
		return "validation_error"
	if isinstance(e, frappe.PermissionError):
		return "permission_denied"
	if isinstance(e, frappe.DoesNotExistError):
		return "not_found"
	if isinstance(e, frappe.AuthenticationError):
		return "authentication_failed"
	if isinstance(e, frappe.SessionStopped):
		return "session_stopped"
	return "server_error"


def _resolve_http_status_code(e):
	code = getattr(e, "http_status_code", 500)
	if isinstance(e, frappe.PermissionError) or isinstance(e, frappe.DoesNotExistError):
		return 403 if isinstance(e, frappe.PermissionError) else 404
	if isinstance(e, (frappe.AuthenticationError, frappe.SessionStopped)):
		return 401
	return code


def _first_server_message(response_data):
	raw = response_data.get("_server_messages")
	if not raw:
		return None
	try:
		messages = json.loads(raw)
		if messages and isinstance(messages, list):
			first = json.loads(messages[0])
			return first.get("message")
	except Exception:
		pass
	return None


def handle_exception(e):
	"""
	Intercepts all exceptions and returns a human-readable JSON response.
	This ensures that even when an error occurs, the API returns a structured
	response that can be easily parsed by the frontend (Flutter).
	"""
	http_status_code = _resolve_http_status_code(e)

	original_response = frappe.utils.response.report_error(http_status_code)

	try:
		response_data = json.loads(original_response.data)
	except Exception:
		response_data = {}

	message = _first_server_message(response_data) or _build_message_from_exception(e)
	error_code = _resolve_error_code(e)

	response_data["status"] = "error"
	response_data["message"] = message
	response_data["error_code"] = error_code

	response = Response(
		json.dumps(response_data),
		status=http_status_code,
		mimetype="application/json",
	)

	if hasattr(frappe.local, "db") and frappe.local.db:
		frappe.local.db.rollback()

	return response
