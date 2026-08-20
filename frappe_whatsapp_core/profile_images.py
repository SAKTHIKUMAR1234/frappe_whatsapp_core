"""Private, permission-scoped contact and team images for the Core workspace."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

import frappe

from frappe_whatsapp_core.permissions import assert_conversation_access, require_core_access

CONTACT_AVATAR_METHOD = "frappe_whatsapp_core.profile_images.download_contact_avatar"
TEAM_AVATAR_METHOD = "frappe_whatsapp_core.profile_images.download_team_avatar"
MAX_AVATAR_BYTES = 5 * 1024 * 1024
ALLOWED_AVATAR_TYPES = {"image/gif", "image/jpeg", "image/png", "image/webp"}


def contact_avatar_url(conversation: str) -> str:
	return f"/api/method/{CONTACT_AVATAR_METHOD}?conversation={quote(str(conversation or ''))}"


def team_avatar_url(team: str) -> str:
	return f"/api/method/{TEAM_AVATAR_METHOD}?team={quote(str(team or ''))}"


def prepare_avatar_file(file_url: str):
	"""Validate an uploaded site-local image before assigning it as an avatar."""
	file_url = _safe_file_url(file_url)
	if not file_url:
		frappe.throw("Select an uploaded image file", frappe.ValidationError)
	name = frappe.db.get_value(
		"File",
		{"file_url": file_url, "is_folder": 0},
		"name",
		order_by="creation desc",
	)
	if not name:
		frappe.throw("Uploaded image was not found", frappe.DoesNotExistError)
	file_doc = frappe.get_doc("File", name)
	frappe.has_permission("File", "read", doc=file_doc, throw=True)
	content_type = _image_content_type(file_doc)
	if content_type not in ALLOWED_AVATAR_TYPES:
		frappe.throw("Avatar must be a PNG, JPEG, WebP, or GIF image", frappe.ValidationError)
	if int(file_doc.get("file_size") or 0) > MAX_AVATAR_BYTES:
		frappe.throw("Avatar image cannot exceed 5 MB", frappe.ValidationError)
	return file_doc


def attach_avatar(file_doc, doctype: str, name: str) -> None:
	file_doc.attached_to_doctype = doctype
	file_doc.attached_to_name = name
	file_doc.attached_to_field = "avatar"
	file_doc.is_private = 1
	file_doc.save(ignore_permissions=True)


@frappe.whitelist()
@require_core_access()
def download_contact_avatar(conversation: str):
	assert_conversation_access(conversation)
	identity = frappe.db.get_value(
		"WhatsApp Core Conversation",
		conversation,
		"remote_identity",
	)
	if not identity:
		frappe.throw("Conversation not found", frappe.DoesNotExistError)
	file_url = frappe.db.get_value("WhatsApp Core Identity", identity, "avatar")
	return _stream_avatar(file_url, "WhatsApp Core Identity", identity)


@frappe.whitelist()
@require_core_access()
def download_team_avatar(team: str):
	if not frappe.db.exists("WhatsApp Core Team", team):
		frappe.throw("Team not found", frappe.DoesNotExistError)
	doc = frappe.get_doc("WhatsApp Core Team", team)
	frappe.has_permission("WhatsApp Core Team", "read", doc=doc, throw=True)
	return _stream_avatar(doc.avatar, "WhatsApp Core Team", doc.name)


def _stream_avatar(file_url: str, doctype: str, name: str):
	file_url = _safe_file_url(file_url)
	if not file_url:
		frappe.throw("Avatar is not available", frappe.DoesNotExistError)
	file_name = frappe.db.get_value(
		"File",
		{
			"file_url": file_url,
			"is_folder": 0,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
		},
		"name",
		order_by="creation desc",
	)
	if not file_name:
		frappe.throw("Avatar file is not available", frappe.DoesNotExistError)
	file_doc = frappe.get_doc("File", file_name)
	content_type = _image_content_type(file_doc)
	if content_type not in ALLOWED_AVATAR_TYPES:
		frappe.throw("Stored avatar is not a supported image", frappe.ValidationError)
	frappe.local.response.filename = Path(file_doc.file_name or "avatar").name
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "download"
	frappe.local.response.content_type = content_type
	frappe.local.response.display_content_as = "inline"


def _safe_file_url(value) -> str:
	value = str(value or "").strip().split("?", 1)[0].split("#", 1)[0]
	if value.startswith(("/files/", "/private/files/")) and "\\" not in value:
		return value
	return ""


def _image_content_type(file_doc) -> str:
	content_type = str(file_doc.get("content_type") or "").strip().lower()
	if content_type in ALLOWED_AVATAR_TYPES:
		return content_type
	return str(mimetypes.guess_type(file_doc.file_name or "")[0] or "").lower()
