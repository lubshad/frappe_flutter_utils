# Copyright (c) 2026, CoreAxis Solutions and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class FlutterDeviceCredential(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		api_key: DF.Data
		api_secret: DF.Password
		device_id_hash: DF.Data
		device_key: DF.Data
		device_name: DF.Data | None
		enabled: DF.Check
		last_login_at: DF.Datetime
		revocation_reason: (
			DF.Literal["", "Device Logout", "Device Limit", "Limit Reduced", "Credential Rotated"] | None
		)
		revoked_at: DF.Datetime | None
		user: DF.Link
	# end: auto-generated types

	pass
