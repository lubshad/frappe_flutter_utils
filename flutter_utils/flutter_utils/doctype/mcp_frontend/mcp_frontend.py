import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import frappe
from frappe.model.document import Document


class MCPFrontend(Document):
	if TYPE_CHECKING:
		from frappe.types import DF
		from flutter_utils.flutter_utils.doctype.mcp_frontend_client.mcp_frontend_client import (
			MCPFrontendClient,
		)

		origin: DF.Data
		enabled: DF.Check
		clients: DF.Table[MCPFrontendClient]

	def validate(self) -> None:
		value = (self.origin or "").strip()
		if not re.fullmatch(r"https?://[a-z0-9.-]+(?::[0-9]+)?", value):
			frappe.throw("Enter an exact frontend origin without a path or trailing slash.")
		parts = urlsplit(value)
		try:
			port = parts.port
		except ValueError:
			frappe.throw("Invalid frontend port.")
		if port == 0 or (
			parts.scheme == "http"
			and parts.hostname not in ("localhost", "127.0.0.1")
			and not parts.hostname.endswith(".localhost")
		):
			frappe.throw("Use HTTPS except for localhost development.")
		self.origin = value
		clients = [row.oauth_client for row in self.clients]
		if len(set(clients)) != len(clients):
			frappe.throw("Each OAuth client can be selected only once.")
