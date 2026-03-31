import json

import frappe
from frappe import _
from werkzeug.wrappers import Response


def handle_exception(e):
	"""
	Intercepts all exceptions and returns a human-readable JSON response.
	This ensures that even when an error occurs, the API returns a structured
	response that can be easily parsed by the frontend (Flutter).
	"""
	http_status_code = getattr(e, "http_status_code", 500)

	# Determine the message
	if isinstance(e, frappe.ValidationError):
		# Clean up ValidationError messages
		parts = str(e).split("ValidationError:")
		message = parts[-1].lstrip(": ").strip() if len(parts) > 1 else str(e)
	elif isinstance(e, frappe.PermissionError):
		message = _("You do not have enough permissions to complete this action.")
		http_status_code = 403
	elif isinstance(e, frappe.DoesNotExistError):
		message = _("The resource you are looking for was not found.")
		http_status_code = 404
	elif isinstance(e, frappe.AuthenticationError):
		message = _("Authentication failed. Please check your credentials.")
		http_status_code = 401
	elif isinstance(e, frappe.SessionStopped):
		message = _("The session has stopped. Please login again.")
		http_status_code = 401
	else:
		# Generic error message for other exceptions
		if frappe.conf.developer_mode:
			parts = str(e).split(": ", 1)
			message = parts[1] if len(parts) > 1 else parts[0]
		else:
			message = _("Something went wrong. Please try again later.")

	# Get the original response from frappe.utils.response.report_error
	# This ensures we have the same structure as the standard Frappe error response.
	original_response = frappe.utils.response.report_error(http_status_code)

	# Load the original response data
	try:
		response_data = json.loads(original_response.data)
	except Exception:
		response_data = {}

	# Add the extra human-readable message key
	response_data["status"] = "error"
	response_data["message"] = message

	# Re-serialize the response data with the extra key
	response = Response(
		json.dumps(response_data),
		status=http_status_code,
		mimetype="application/json",
	)

	# Rollback database changes
	if hasattr(frappe.local, "db") and frappe.local.db:
		frappe.local.db.rollback()

	return response
