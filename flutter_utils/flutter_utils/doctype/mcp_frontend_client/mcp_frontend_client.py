from typing import TYPE_CHECKING

from frappe.model.document import Document


class MCPFrontendClient(Document):
	if TYPE_CHECKING:
		from frappe.types import DF

		oauth_client: DF.Link
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
