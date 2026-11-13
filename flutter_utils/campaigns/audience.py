"""Metadata-validated User audiences. Never accept arbitrary query field paths."""

from typing import Any

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate

TEXT_TYPES = {"Data", "Select", "Link", "Autocomplete"}
NUMBER_TYPES = {"Int", "Float", "Currency", "Percent", "Check"}
DATE_TYPES = {"Date", "Datetime"}
BLOCKED = {"api_key", "api_secret", "reset_password_key", "reset_password_key_generated_on"}


def fields() -> dict[str, Any]:
	return {
		field.fieldname: field
		for field in frappe.get_meta("User").fields
		if field.fieldtype in TEXT_TYPES | NUMBER_TYPES | DATE_TYPES
		and not field.hidden
		and not field.is_virtual
		and not field.permlevel
		and field.fieldname not in BLOCKED
		and not any(word in field.fieldname.lower() for word in ("password", "secret", "token", "otp"))
	}


def operators(field: Any) -> list[str]:
	result = ["=", "!=", "in", "not in", "is set", "is not set"]
	if field.fieldtype in NUMBER_TYPES | DATE_TYPES:
		result += [">", ">=", "<", "<="]
	if field.fieldtype == "Data":
		result += ["contains"]
	return result


def _value(field: Any, value: str) -> Any:
	if field.fieldtype in NUMBER_TYPES:
		try:
			import math

			number = float(value)
			if not math.isfinite(number):
				raise ValueError
			if field.fieldtype in {"Int", "Check"} and not number.is_integer():
				raise ValueError
			if field.fieldtype == "Check" and number not in (0, 1):
				raise ValueError
			return number
		except ValueError, TypeError:
			frappe.throw(_("Enter a valid number for {0}.").format(field.label))
	if field.fieldtype in DATE_TYPES:
		try:
			return str(getdate(value) if field.fieldtype == "Date" else get_datetime(value))
		except ValueError, TypeError:
			frappe.throw(_("Enter a valid date for {0}.").format(field.label))
	return value


def query(campaign: Any) -> dict[str, Any]:
	available = fields()
	conditions = []
	if campaign.match_mode not in {"All", "Any"}:
		frappe.throw(_("Choose All or Any for audience matching."))
	if len(campaign.audience_filters or []) > 30:
		frappe.throw(_("Use at most 30 audience conditions."))
	for row in campaign.audience_filters or []:
		field = available.get(row.user_field)
		if not field or row.operator not in operators(field):
			frappe.throw(_("Unsupported User field or filter operator."))
		value = str(row.value).strip() if row.value is not None else ""
		operator = row.operator
		if operator in {"is set", "is not set"}:
			operator, value = "is", "set" if operator == "is set" else "not set"
		elif not value or len(value) > 2000:
			frappe.throw(_("Each condition needs a value of at most 2000 characters."))
		elif operator in {"in", "not in"}:
			value = [_value(field, item.strip()) for item in value.split(",") if item.strip()]
			if not value:
				frappe.throw(_("Enter at least one filter value."))
		elif operator == "contains":
			operator, value = "like", f"%{value}%"
		else:
			value = _value(field, value)
		conditions.append(["User", row.user_field, operator, value])
	base = [["User", "enabled", "=", 1], ["User", "name", "not in", ["Guest", "Administrator"]]]
	return {
		"filters": base + (conditions if campaign.match_mode == "All" else []),
		"or_filters": conditions if campaign.match_mode == "Any" else [],
	}
