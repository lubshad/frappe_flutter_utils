import base64
import hashlib
import json
import secrets
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

import frappe
from frappe.integrations.oauth2 import get_oauth_server
from frappe.tests.test_api import make_request
from frappe.utils import get_test_client
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from flutter_utils.api import mcp_consent as consent


class TestMcpConsent(unittest.TestCase):
	def test_connector_lifecycle(self):
		frappe.set_user("Administrator")
		origin = "https://admin.example.test"
		callback = "https://connector.example.test/callback"
		client = frappe.get_doc(
			dict(
				doctype="OAuth Client",
				app_name="Temporary MCP test",
				scopes="all",
				redirect_uris=callback,
				default_redirect_uri=callback,
				token_endpoint_auth_method="None",
				grant_type="Authorization Code",
				response_type="Code",
			)
		).insert()
		try:
			verifier = secrets.token_urlsafe(40)
			challenge = (
				base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
			)
			params = dict(
				client_id=client.name,
				redirect_uri=callback,
				state="expected",
				response_type="code",
				code_challenge=challenge,
				code_challenge_method="S256",
			)
			request = Request(
				EnvironBuilder(
					query_string=params, headers={"Origin": origin, "X-MCP-Frontend": origin}
				).get_environ()
			)
			with (
				patch.dict(frappe.conf, flutter_mcp_frontends={origin: [client.name]}),
				patch.object(frappe.local, "request", request, create=True),
			):
				self.assertEqual(consent.resource_metadata().json["resource"], origin + "/api/v2/mcp")
				for allow in (False, True):
					handle = parse_qs(urlsplit(consent.start().location).query)["request"][0]
					self.assertEqual(consent.review(handle)["client"], client.app_name)
					query = parse_qs(urlsplit(consent.decide(handle, allow)["callback"]).query)
					self.assertEqual(query["state"], ["expected"])
					with self.assertRaises(frappe.ValidationError):
						consent.decide(handle, allow)
					if not allow:
						self.assertEqual(query["error"], ["access_denied"])
				_, body, status = get_oauth_server().create_token_response(
					origin + "/mcp/token",
					"POST",
					urlencode(
						dict(
							grant_type="authorization_code",
							code=query["code"][0],
							client_id=client.name,
							code_verifier=verifier,
							redirect_uri=callback,
						)
					),
					{"Content-Type": "application/x-www-form-urlencoded"},
				)
				self.assertEqual(status, 200)
				frappe.db.commit()
				response = make_request(
					get_test_client(use_cookies=False).open,
					args=(),
					kwargs=dict(
						path="/api/v2/mcp",
						method="POST",
						headers={
							"Authorization": "Bearer " + json.loads(body)["access_token"],
							"Accept": "application/json",
						},
						json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1},
					),
					site=frappe.local.site,
				)
				self.assertEqual(response.status_code, 200)
				self.assertIn("tools", response.json["result"])
		finally:
			for dt in ("OAuth Bearer Token", "OAuth Authorization Code"):
				frappe.db.delete(dt, {"client": client.name})
			frappe.delete_doc("OAuth Client", client.name, ignore_permissions=True)
			frappe.db.commit()
