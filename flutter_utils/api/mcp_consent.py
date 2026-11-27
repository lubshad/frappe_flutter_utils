"""Opt-in frontend consent for pre-registered Frappe OAuth clients."""

import json
import re
import secrets
from urllib.parse import urlencode, urlsplit

import frappe
from frappe.integrations.oauth2 import get_oauth_server
from frappe.permissions import SYSTEM_USER_ROLE
from oauthlib.common import add_params_to_uri
from werkzeug.wrappers import Response


def _config(origin):
	frontend = origin and frappe.db.get_value(
		"MCP Frontend", {"origin": origin, "enabled": 1}, ["name", "origin"], as_dict=True
	)
	if not frontend or frontend.origin != origin:
		frappe.throw("Frontend not configured", frappe.PermissionError)
	return frappe.get_all(
		"MCP Frontend Client",
		filters={"parenttype": "MCP Frontend", "parentfield": "clients", "parent": frontend.name},
		pluck="oauth_client",
	)


def _origin():
	origin = frappe.get_request_header("X-MCP-Frontend")
	_config(origin)
	return origin


@frappe.whitelist(allow_guest=True, methods=["GET"])
def resource_metadata():
	origin = _origin()
	return Response(
		json.dumps({"resource": origin + "/api/v2/mcp", "authorization_servers": [origin]}),
		mimetype="application/json",
	)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def server_metadata():
	origin = _origin()
	return Response(
		json.dumps(
			dict(
				issuer=origin,
				authorization_endpoint=origin + "/mcp/authorize",
				token_endpoint=origin + "/mcp/token",
				response_types_supported=["code"],
				grant_types_supported=["authorization_code", "refresh_token"],
				code_challenge_methods_supported=["S256"],
				token_endpoint_auth_methods_supported=["none", "client_secret_basic"],
			)
		),
		mimetype="application/json",
	)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def start(**kwargs):
	origin = _origin()
	args = frappe.request.args
	if any(len(args.getlist(k)) != 1 for k in args):
		frappe.throw("Duplicate authorization parameter")
	p = {
		k: args[k]
		for k in (
			"client_id",
			"redirect_uri",
			"state",
			"scope",
			"response_type",
			"code_challenge",
			"code_challenge_method",
			"resource",
		)
		if k in args
	}
	client = p.get("client_id")
	if client not in _config(origin) or p.get("resource", origin + "/api/v2/mcp") != origin + "/api/v2/mcp":
		frappe.throw("Invalid client or resource", frappe.PermissionError)
	redirect = p.get("redirect_uri", "")
	if (
		not redirect
		or urlsplit(redirect).scheme not in ("https", "http")
		or redirect not in (frappe.db.get_value("OAuth Client", client, "redirect_uris") or "").split()
	):
		frappe.throw("Unregistered callback")
	if (
		p.get("response_type") != "code"
		or p.get("code_challenge_method") != "S256"
		or not re.fullmatch(r"[\w-]{43}", p.get("code_challenge", ""), re.ASCII)
	):
		frappe.throw("Authorization code with S256 PKCE required")
	handle = secrets.token_urlsafe(32)
	frappe.cache.set_value("flutter-mcp:" + handle, (origin, p), expires_in_sec=300)
	return Response(
		status=302,
		headers={
			"Location": origin + "/mcp/approve?request=" + handle,
			"Cache-Control": "no-store",
			"Referrer-Policy": "no-referrer",
		},
	)


def _pending(request):
	if not re.fullmatch(r"[\w-]{43}", request or "", re.ASCII) or SYSTEM_USER_ROLE not in frappe.get_roles():
		frappe.throw("MCP access denied", frappe.PermissionError)
	key = "flutter-mcp:" + request
	value = frappe.cache.get_value(key)
	if not value:
		frappe.throw("Request expired. Reconnect from the connector.")
	origin, p = value
	if frappe.get_request_header("Origin") != origin or p["client_id"] not in _config(origin):
		frappe.throw("Frontend mismatch", frappe.PermissionError)
	uri = origin + "/mcp/authorize?" + urlencode(p)
	server = get_oauth_server()
	scopes, credentials = server.validate_authorization_request(uri, "GET", None, {})
	return key, p, uri, server, scopes, credentials


@frappe.whitelist(methods=["POST"])
def review(request: str):
	_, p, _, _, scopes, _ = _pending(request)
	return {
		"client": frappe.db.get_value("OAuth Client", p["client_id"], "app_name"),
		"user": frappe.session.user,
		"scopes": scopes,
	}


@frappe.whitelist(methods=["POST"])
def decide(request: str, allow: bool):
	key, p, uri, server, scopes, credentials = _pending(request)
	if not frappe.cache.delete(frappe.cache.make_key(key)):
		frappe.throw("Request already completed")
	if not allow:
		params = [("error", "access_denied")]
		if "state" in p:
			params.append(("state", p["state"]))
		return {"callback": add_params_to_uri(p["redirect_uri"], params)}
	headers, _, _ = server.create_authorization_response(
		uri, http_method="GET", scopes=scopes, credentials=credentials
	)
	return {"callback": headers["Location"]}
