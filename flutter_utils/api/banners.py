from typing import Any

import frappe
from frappe.utils.verified_command import get_signed_params


def get_signed_image_url_map(image_urls: list[str]) -> dict[str, str]:
	normalized_urls = {
		image_url.strip()
		for image_url in image_urls
		if isinstance(image_url, str) and image_url.strip()
	}
	public_urls = {
		image_url
		for image_url in normalized_urls
		if image_url.startswith("/") and not image_url.startswith(("/files/", "/private/files/"))
	}
	file_urls = {
		image_url
		for image_url in normalized_urls
		if image_url.startswith(("/files/", "/private/files/"))
	}
	if not file_urls and not public_urls:
		return {}

	files = (
		frappe.get_all(
			"File",
			filters={"file_url": ["in", list(file_urls)]},
			fields=["file_url", "is_private"],
		)
		if file_urls
		else []
	)
	download_endpoint = frappe.utils.get_url("/api/method/frappe.utils.file_manager.download_file")

	signed_file_map = {
		file.file_url: (
			f"{download_endpoint}?{get_signed_params({'file_url': file.file_url})}"
			if file.is_private
			else frappe.utils.get_url(file.file_url)
		)
		for file in files
		if file.file_url
	}
	public_url_map = {url: frappe.utils.get_url(url) for url in public_urls}
	found_file_urls = set(signed_file_map)
	missing_public_file_map = {
		url: frappe.utils.get_url(url)
		for url in file_urls - found_file_urls
		if url.startswith("/files/")
	}
	missing_private_file_map = {
		url: "" for url in file_urls - found_file_urls if url.startswith("/private/files/")
	}

	return {
		**public_url_map,
		**missing_public_file_map,
		**missing_private_file_map,
		**signed_file_map,
	}


def _get_default_banner_slideshow() -> str:
	if not frappe.db.exists("DocType", "Flutter Utils Settings"):
		return ""

	value = frappe.db.get_single_value("Flutter Utils Settings", "default_banner_slideshow")
	return value.strip() if isinstance(value, str) else ""


def _get_slideshow_name(slideshow: str | None) -> str:
	if isinstance(slideshow, str) and slideshow.strip():
		return slideshow.strip()
	return _get_default_banner_slideshow()


def _get_item_value(item: Any, fieldname: str) -> str:
	value = item.get(fieldname) if hasattr(item, "get") else getattr(item, fieldname, "")
	return value if isinstance(value, str) else ""


def _serialize_slideshow_item(item: Any, signed_image_url_map: dict[str, str]) -> dict[str, str]:
	image = _get_item_value(item, "image")

	return {
		"id": _get_item_value(item, "name"),
		"title": _get_item_value(item, "heading"),
		"description": _get_item_value(item, "description"),
		"image": signed_image_url_map.get(image, image or ""),
		"url": _get_item_value(item, "url"),
	}


@frappe.whitelist(allow_guest=True)
def get_banners(slideshow: str | None = None) -> list[dict[str, str]]:
	slideshow_name = _get_slideshow_name(slideshow)
	if not slideshow_name:
		return []

	if not frappe.db.table_exists("Website Slideshow") or not frappe.db.exists(
		"Website Slideshow", slideshow_name
	):
		return []

	doc = frappe.get_doc("Website Slideshow", slideshow_name)
	items = sorted(doc.get("slideshow_items") or [], key=lambda item: item.idx or 0)
	image_urls = [image for item in items if (image := _get_item_value(item, "image"))]
	signed_image_url_map = get_signed_image_url_map(image_urls)

	return [_serialize_slideshow_item(item, signed_image_url_map) for item in items]
