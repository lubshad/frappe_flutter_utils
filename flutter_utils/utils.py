import frappe.app

from flutter_utils.flutter_utils.handler import handle_exception as custom_handle_exception


def patch_exception_handler():
	"""
	Patches Frappe's default exception handler with the Flutter-friendly one.
	Called on every request via before_request hook, but only patches once.
	"""
	if frappe.app.handle_exception is not custom_handle_exception:
		frappe.app.handle_exception = custom_handle_exception
