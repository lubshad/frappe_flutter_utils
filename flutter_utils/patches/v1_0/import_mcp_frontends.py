# Preserve existing site allowlists on upgrade; Desk owns all subsequent edits.
import frappe


def execute() -> None:
	for origin, clients in (frappe.conf.get("flutter_mcp_frontends") or {}).items():
		if not isinstance(clients, list) or frappe.db.exists("MCP Frontend", {"origin": origin}):
			continue
		doc = frappe.new_doc("MCP Frontend")
		doc.origin = origin
		for client in dict.fromkeys(clients):
			if frappe.db.exists("OAuth Client", client):
				doc.append("clients", {"oauth_client": client})
		doc.insert(ignore_permissions=True)
