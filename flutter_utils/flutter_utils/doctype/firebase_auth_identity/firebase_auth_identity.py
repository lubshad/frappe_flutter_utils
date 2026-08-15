# Copyright (c) 2026, CoreAxis Solutions and contributors
# For license information, please see license.txt

import hashlib

from frappe.model.document import Document


class FirebaseAuthIdentity(Document):
	def autoname(self) -> None:
		self.identity_key = _build_identity_key(self.firebase_project_id, self.firebase_uid)
		self.name = self.identity_key


def _build_identity_key(project_id: str, firebase_uid: str) -> str:
	return hashlib.sha256(f"{project_id}:{firebase_uid}".encode()).hexdigest()
