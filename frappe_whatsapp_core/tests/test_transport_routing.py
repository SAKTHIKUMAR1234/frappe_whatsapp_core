from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from frappe_whatsapp_core.hub_client import (
	_MANAGEMENT_METHODS,
	_RELAY_OPERATIONS,
	_relay_request,
	call_action,
	call_management,
	delete_media,
	download_media,
	get_call_permission,
	get_media_url,
	publish_outbound_command,
	send_account_raw,
	send_batch,
	upload_media,
)


def _settings():
	return SimpleNamespace(
		enabled=1,
		outbound_enabled=1,
		hub_url="https://hub.example.test",
		relay_url="https://relay.example.test",
		request_timeout=30,
		accounts=[SimpleNamespace(account_name="Hub Account")],
		get_hub_auth_headers=lambda: {
			"Authorization": "token core-key:core-secret",
			"Content-Type": "application/json",
		},
		get_account_name=lambda _channel: "Hub Account",
	)


def _json_response(payload, *, ok=True, status_code=200):
	response = MagicMock(ok=ok, status_code=status_code)
	response.json.return_value = payload
	response.text = ""
	response.headers = {"Content-Type": "application/json"}
	response.content = b""
	return response


class TestTransportRouting(FrappeTestCase):
	def test_route_allowlists_are_complete_and_have_no_generic_escape_hatch(self):
		self.assertEqual(
			set(_RELAY_OPERATIONS),
			{
				"call_action",
				"call_permission",
				"command",
				"media_content",
				"media_delete",
				"media_info",
				"media_upload",
				"outbound",
				"outbound_batch",
			},
		)
		self.assertEqual(
			_MANAGEMENT_METHODS,
			frozenset(
				{
					"calling.build_call_deep_link",
					"calling.get_call_settings",
					"calling.update_call_settings",
					"flow_endpoint.provision",
					"flow_endpoint.status",
					"groups.approve_join_requests",
					"groups.create_group",
					"groups.delete_group",
					"groups.get_group",
					"groups.get_invite_link",
					"groups.list_groups",
					"groups.list_join_requests",
					"groups.reject_join_requests",
					"groups.remove_participants",
					"groups.reset_invite_link",
					"groups.update_group",
					"groups.update_group_picture",
					"meta_flows.create_flow",
					"meta_flows.delete_flow",
					"meta_flows.deprecate_flow",
					"meta_flows.get_business_public_key",
					"meta_flows.get_flow",
					"meta_flows.get_flow_json",
					"meta_flows.list_flow_assets",
					"meta_flows.list_flows",
					"meta_flows.migrate_flows",
					"meta_flows.publish_flow",
					"meta_flows.set_business_public_key",
					"meta_flows.update_flow_metadata",
					"meta_flows.upload_flow_json",
					"onboarding.get_account_meta_context",
					"onboarding.list_site_accounts",
					"templates.upsert_template_for_site",
				}
			),
		)

	def test_management_uses_exact_allowlist_and_current_hub_namespace(self):
		response = _json_response({"message": {"accounts": []}})
		with (
			patch("frappe_whatsapp_core.hub_client.get_settings", return_value=_settings()),
			patch("frappe_whatsapp_core.hub_client._session.post", return_value=response) as post,
		):
			result = call_management(
				"frappe_whatsapp_integration.frappe_whatsapp_hub.api.onboarding.list_site_accounts"
			)
		self.assertEqual(result, {"accounts": []})
		self.assertEqual(
			post.call_args.args[0],
			"https://hub.example.test/api/method/"
			"frappe_whatsapp_hub.frappe_whatsapp_hub.api.onboarding.list_site_accounts",
		)

		for forbidden in (
			"frappe_whatsapp_hub.frappe_whatsapp_hub.api.media.download_media",
			"frappe_whatsapp_hub.frappe_whatsapp_hub.api.gateway.outbound",
			"frappe_whatsapp_hub.frappe_whatsapp_hub.api.templates.__dict__",
		):
			with self.assertRaises(frappe.ValidationError):
				call_management(forbidden)

	def test_every_operational_method_uses_only_fixed_relay_routes(self):
		settings = _settings()
		json_ok = _json_response({"success": True})
		upload_ok = _json_response({"success": True, "media_id": "MEDIA-1"})
		info_ok = _json_response({
			"success": True,
			"url": "https://meta.example.test/media",
			"mime_type": "image/png",
		})
		content_ok = _json_response({})
		content_ok.content = b"image-bytes"
		content_ok.headers = {"Content-Type": "image/png"}
		with (
			patch("frappe_whatsapp_core.hub_client.get_settings", return_value=settings),
			patch(
				"frappe_whatsapp_core.hub_client._session.post",
				side_effect=[json_ok, json_ok, json_ok, json_ok, upload_ok],
			) as post,
			patch(
				"frappe_whatsapp_core.hub_client._session.get",
				side_effect=[json_ok, info_ok, content_ok],
			) as get,
			patch(
				"frappe_whatsapp_core.hub_client._session.delete",
				return_value=json_ok,
			) as delete,
		):
			send_account_raw(
				"Hub Account",
				{"type": "text", "to": "919876543210", "text": {"body": "hello"}},
				"message-1",
			)
			call_action(
				"Hub Account",
				{
					"messaging_product": "whatsapp", "action": "reject", "call_id": "CALL-1",
				},
			)
			send_batch([{
				"channel": "CHANNEL-1",
				"payload": {"type": "text", "to": "919876543210", "text": {"body": "batch"}},
				"idempotency_key": "batch-1",
			}])
			publish_outbound_command("command-1", [{
				"channel": "CHANNEL-1",
				"payload": {"type": "text", "to": "919876543210", "text": {"body": "command"}},
				"idempotency_key": "command-message-1",
			}])
			get_call_permission("Hub Account", user_wa_id="919876543210")
			upload_media(
				"Hub Account", b"image-bytes", content_type="image/png", filename="photo.png",
			)
			get_media_url("Hub Account", "MEDIA-1")
			self.assertEqual(download_media("Hub Account", "MEDIA-1")["content"], b"image-bytes")
			delete_media("Hub Account", "MEDIA-1")

		self.assertEqual(
			[call.args[0] for call in post.call_args_list],
			[
				"https://relay.example.test/v1/outbound",
				"https://relay.example.test/v1/meta/calls",
				"https://relay.example.test/v1/outbound/batch",
				"https://relay.example.test/v1/commands/outbound",
				"https://relay.example.test/v1/meta/media",
			],
		)
		self.assertEqual(
			[call.args[0] for call in get.call_args_list],
			[
				"https://relay.example.test/v1/meta/call-permissions",
				"https://relay.example.test/v1/meta/media/MEDIA-1",
				"https://relay.example.test/v1/meta/media/MEDIA-1/content",
			],
		)
		delete.assert_called_once()
		self.assertEqual(
			delete.call_args.args[0],
			"https://relay.example.test/v1/meta/media/MEDIA-1",
		)
		for call in [*post.call_args_list, *get.call_args_list, *delete.call_args_list]:
			self.assertNotIn("/api/method/", call.args[0])

	def test_relay_client_rejects_unknown_operations_and_media_paths(self):
		settings = _settings()
		with self.assertRaises(frappe.ValidationError):
			_relay_request("generic_meta_proxy", settings=settings)
		with self.assertRaises(frappe.ValidationError):
			_relay_request(
				"media_info", settings=settings, media_id="../credential",
			)
