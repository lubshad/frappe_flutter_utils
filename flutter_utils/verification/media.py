"""Bounded ISO-BMFF validation, not video decoding or automated identity analysis."""

from __future__ import annotations

import frappe
from frappe import _

SUPPORTED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "mp4"}
VIDEO_CODECS = {b"avc1", b"avc3", b"hvc1", b"hev1", b"mp4v", b"vp09", b"av01"}
MP4_BRANDS = {
	b"isom",
	b"iso2",
	b"iso3",
	b"iso4",
	b"iso5",
	b"iso6",
	b"mp41",
	b"mp42",
	b"avc1",
	b"M4V ",
	b"dash",
}


def _boxes(data: memoryview) -> list[tuple[bytes, memoryview]]:
	result = []
	offset = 0
	while offset < len(data):
		if len(data) - offset < 8 or len(result) >= 10000:
			frappe.throw(_("Invalid MP4 container."))
		size = int.from_bytes(data[offset : offset + 4], "big")
		kind = bytes(data[offset + 4 : offset + 8])
		header = 8
		if size == 1:
			if len(data) - offset < 16:
				frappe.throw(_("Invalid MP4 container."))
			size = int.from_bytes(data[offset + 8 : offset + 16], "big")
			header = 16
		elif size == 0:
			size = len(data) - offset
		if size < header or size > len(data) - offset:
			frappe.throw(_("Invalid MP4 container."))
		result.append((kind, data[offset + header : offset + size]))
		offset += size
	return result


def _children(boxes: list[tuple[bytes, memoryview]], kind: bytes) -> list[memoryview]:
	return [payload for name, payload in boxes if name == kind]


def validate_mp4(content: bytes) -> None:
	boxes = _boxes(memoryview(content))
	brands = _children(boxes, b"ftyp")
	if len(brands) != 1 or len(brands[0]) < 8 or (len(brands[0]) - 8) % 4:
		frappe.throw(_("Evidence is not a supported MP4 video."))
	brand = brands[0]
	declared = {bytes(brand[:4]), *(bytes(brand[index : index + 4]) for index in range(8, len(brand), 4))}
	if not declared.intersection(MP4_BRANDS) or not any(len(data) for data in _children(boxes, b"mdat")):
		frappe.throw(_("Evidence is not a supported MP4 video."))
	for movie in _children(boxes, b"moov"):
		for track in _children(_boxes(movie), b"trak"):
			for media in _children(_boxes(track), b"mdia"):
				children = _boxes(media)
				if not any(
					len(handler) >= 12 and bytes(handler[8:12]) == b"vide"
					for handler in _children(children, b"hdlr")
				):
					continue
				for info in _children(children, b"minf"):
					for table in _children(_boxes(info), b"stbl"):
						for description in _children(_boxes(table), b"stsd"):
							if len(description) < 8:
								continue
							entries = _boxes(description[8:])
							if int.from_bytes(description[4:8], "big") != len(entries):
								frappe.throw(_("Invalid MP4 video track."))
							for codec, entry in entries:
								if (
									codec in VIDEO_CODECS
									and len(entry) >= 78
									and int.from_bytes(entry[24:26], "big")
									and int.from_bytes(entry[26:28], "big")
								):
									return
	frappe.throw(_("MP4 evidence must contain a supported video track, not audio only."))
