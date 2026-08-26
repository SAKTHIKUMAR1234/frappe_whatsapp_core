import json
import uuid
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from frappe_whatsapp_core.frontend_api import (
	_i2a_schema_available,
	_validated_hub_account_mappings,
	ai_queue_workspace,
	bootstrap,
	classify_messages,
	connectors_workspace,
	contact_source_doctypes,
	contact_source_fields,
	discover_hub_accounts,
	health_workspace,
	polls_workspace,
	save_ai_summary_settings,
	save_contact_source,
	settings_workspace,
)
from frappe_whatsapp_core.materializer import (
	get_or_create_channel,
	get_or_create_conversation,
	get_or_create_identity,
)


class TestFrontendWorkspaces(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = str(uuid.uuid4().int)[-12:]

	def test_ai_queue_classifies_selected_messages(self):
		channel = get_or_create_channel(f"UI-{self.suffix}", "WABA-UI")
		conversation = get_or_create_conversation(
			channel,
			get_or_create_identity(f"93{self.suffix[-10:]}"),
		)
		message = frappe.get_doc({
			"doctype": "WhatsApp Core Message",
			"message_key": f"ui-message-{self.suffix}",
			"conversation": conversation.name,
			"channel": channel.name,
			"provider_message_id": f"wamid.ui.{self.suffix}",
			"direction": "Inbound",
			"message_type": "text",
			"body": "Damaged goods need a credit note",
			"content": "{}",
			"provider_timestamp": now_datetime(),
			"delivery_status": "Received",
		}).insert(ignore_permissions=True)

		before = ai_queue_workspace(limit=250)
		self.assertIn(message.name, {row.name for row in before["messages"]})

		topic = classify_messages(
			conversation.name,
			"Credit note request",
			[message.name],
			category="Complaint",
		)
		self.assertEqual(topic.source, "Manual")

		after = ai_queue_workspace(limit=250)
		self.assertNotIn(message.name, {row.name for row in after["messages"]})

	def test_connector_registry_reports_real_contracts(self):
		workspace = connectors_workspace()
		self.assertTrue(workspace["mcp_endpoint"].endswith("mcp_transport.handle"))
		self.assertGreaterEqual(workspace["metrics"]["mcp_tools"], 1)
		self.assertIn("case.create", workspace["flow_actions"])
		self.assertEqual(
			{row["label"] for row in workspace["extension_points"]},
			{
				"Party resolution",
				"Party search",
				"Outbound preflight",
				"Campaign preflight",
				"Campaign sender",
			},
		)

	def test_poll_workspace_is_derived_from_question_nodes(self):
		flow = frappe.get_doc({
			"doctype": "WhatsApp Core Flow",
			"flow_key": f"ui.poll.{self.suffix}",
			"title": "UI Poll",
			"status": "Draft",
			"enabled": 1,
			"draft_graph": json.dumps({
				"schema_version": 1,
				"triggers": [],
				"nodes": [
					{"id": "start", "type": "start", "config": {}},
					{
						"id": "choice",
						"type": "ask_choice",
						"config": {
							"message": "Choose one",
							"answer_key": "choice",
							"options": [
								{"label": "Yes", "value": "yes"},
								{"label": "No", "value": "no"},
							],
						},
					},
					{"id": "end", "type": "end", "config": {}},
				],
				"edges": [],
			}),
		}).insert(ignore_permissions=True)

		workspace = polls_workspace()
		row = next(item for item in workspace["flows"] if item["name"] == flow.name)
		self.assertEqual(row["question_count"], 1)
		self.assertEqual(row["choice_count"], 1)

	def test_health_and_settings_use_site_local_records(self):
		health = health_workspace()
		self.assertEqual(
			set(health["metrics"]),
			{
				"pending_events",
				"failed_events",
				"failed_flow_steps",
				"failed_messages",
			},
		)

	def test_operational_manager_cannot_read_backend_configuration(self):
		email = f"whatsapp-manager-{self.suffix}@example.com"
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": "WhatsApp Manager",
			"enabled": 1,
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		user.add_roles("WhatsApp Manager")
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			settings_workspace()
		frappe.set_user("Administrator")

	def test_bootstrap_exposes_operations_not_configuration_builders(self):
		boot = bootstrap()
		self.assertTrue({"inbox", "templates", "campaigns", "groups", "calling"} <= set(boot["modules"]))
		self.assertFalse(
			{"settings", "connectors", "polls", "automation-flows"} & set(boot["modules"])
		)
		settings = settings_workspace()
		self.assertEqual(settings["site"], frappe.local.site)
		self.assertEqual(settings["product"]["version"], "2.0.0")
		self.assertEqual(settings["product"]["transport_contract_version"], 3)
		self.assertIn("ai_summary", settings)
		self.assertIn("i2a_actions", settings)
		self.assertEqual(
			set(settings["inventory"]),
			{
				"identities",
				"verified_bindings",
				"conversations",
				"messages",
			},
		)

	def test_core_settings_provisions_one_unified_service_credential(self):
		script = (
			Path(__file__).resolve().parents[1]
			/ "frappe_whatsapp_core"
			/ "doctype"
			/ "whatsapp_core_settings"
			/ "whatsapp_core_settings.js"
		).read_text()
		self.assertIn('frappe.user.has_role("System Manager")', script)
		self.assertIn('__("Generate Integration Credential")', script)
		self.assertIn("provision_transport_credentials", script)
		self.assertIn('capability: "all"', script)
		self.assertNotIn('capability: "ingress"', script)

	def test_shared_fields_and_dialogs_are_used_instead_of_runtime_primevue_variants(self):
		ui_root = Path(__file__).resolve().parents[2] / "core_ui" / "src"
		vue_files = list(ui_root.rglob("*.vue"))
		allowed = {
			ui_root / "components" / "AppDialog.vue",
			ui_root / "components" / "form" / "LinkField.vue",
			ui_root / "components" / "form" / "MultiLinkField.vue",
		}
		violations = []
		for path in vue_files:
			if path in allowed:
				continue
			content = path.read_text()
			for import_path in (
				"primevue/dialog",
				"primevue/autocomplete",
				"primevue/multiselect",
			):
				if import_path in content:
					violations.append(f"{path.relative_to(ui_root)} imports {import_path}")
		self.assertEqual(violations, [])

	def test_workspace_routes_mount_directly_without_fragment_transitions(self):
		shell = (
			Path(__file__).resolve().parents[2]
			/ "core_ui"
			/ "src"
			/ "layouts"
			/ "AppShell.vue"
		).read_text()
		self.assertIn(':key="routeComponentKey(activeRoute)"', shell)
		self.assertNotIn('<Transition name="workspace-view"', shell)
		self.assertNotIn(".workspace-view-enter-active", shell)

	def test_inbox_marks_only_the_settled_visible_message_window(self):
		inbox = (
			Path(__file__).resolve().parents[2]
			/ "core_ui"
			/ "src"
			/ "features"
			/ "inbox"
			/ "views"
			/ "InboxView.vue"
		).read_text()
		self.assertIn("pendingReadMessages.set(conversation, visibleNames)", inbox)
		self.assertIn("window.setTimeout(flushReadBatch, 400)", inbox)
		self.assertIn("message.optimistic", inbox)
		self.assertIn("name.startsWith('optimistic:')", inbox)
		self.assertIn("document.visibilityState !== 'visible'", inbox)
		self.assertIn("async function loadLatestMessages()", inbox)
		self.assertIn("'Scroll to bottom'", inbox)
		# Opening a chat acknowledges its list badge for this browser, while the
		# exact per-message ledger above still records only settled visible rows.
		self.assertIn("function clearConversationBadge(name)", inbox)
		self.assertIn("if (row) row.unread_count = 0", inbox)

	def test_inbox_applies_complete_realtime_deltas_without_refetching(self):
		inbox = (
			Path(__file__).resolve().parents[2]
			/ "core_ui"
			/ "src"
			/ "features"
			/ "inbox"
			/ "views"
			/ "InboxView.vue"
		).read_text()
		batch_handler = inbox.split("function refreshCommittedBatch(event)", 1)[1].split(
			"async function refreshVisibleMessages()", 1
		)[0]
		self.assertIn("batch?.conversation_rows", batch_handler)
		self.assertIn("upsertConversationRow(row)", batch_handler)
		self.assertIn("openRealtimeServiceWindow(", batch_handler)
		self.assertIn("detail.value.outbound.text_allowed = true", inbox)
		self.assertIn(
			"detail.value.outbound.text_ready = Boolean(detail.value.outbound.ready)",
			inbox,
		)
		self.assertIn("allowAppend: isCreated", batch_handler)
		self.assertIn("alreadyLoaded", batch_handler)
		self.assertNotIn("hydrateConversationRow", batch_handler)
		self.assertIn("if (!needsCompatibilityReload) return", batch_handler)
		self.assertIn("subscribeConnection", inbox)
		self.assertIn("unsubscribers.forEach((unsubscribe) => unsubscribe())", inbox)
		realtime = (
			Path(__file__).resolve().parents[2]
			/ "core_ui"
			/ "src"
			/ "services"
			/ "realtime.js"
		).read_text()
		self.assertIn("activeConsumers", realtime)
		self.assertIn("socket.disconnect()", realtime)
		self.assertIn("releaseConnection()", realtime)

	def test_new_chat_does_not_require_or_auto_select_a_template(self):
		inbox = (
			Path(__file__).resolve().parents[2]
			/ "core_ui"
			/ "src"
			/ "features"
			/ "inbox"
			/ "views"
			/ "InboxView.vue"
		).read_text()
		self.assertIn("mode: 'message'", inbox)
		self.assertIn("newChat.value.mode === 'template' ? newChat.value.template : ''", inbox)
		self.assertIn("newChat.mode === 'template' && !newChat.template", inbox)
		self.assertNotIn("Start and queue", inbox)

	def test_reader_details_use_a_viewport_panel_and_formatted_identities(self):
		bubble = (
			Path(__file__).resolve().parents[2]
			/ "core_ui"
			/ "src"
			/ "features"
			/ "inbox"
			/ "components"
			/ "MessageBubble.vue"
		).read_text()
		self.assertIn('<Teleport to="body">', bubble)
		self.assertIn("formatDateTime(readAt, '')", bubble)
		self.assertIn("reader-panel", bubble)
		self.assertIn('role="dialog"', bubble)
		self.assertIn("Waiting on", bubble)
		self.assertNotIn("reader-tooltip-overlay", bubble)

	def test_document_references_use_shared_link_components(self):
		ui_root = Path(__file__).resolve().parents[2] / "core_ui" / "src"
		inbox = (ui_root / "features/inbox/views/InboxView.vue").read_text()
		template_send = (
			ui_root / "features/templates/components/TemplateSendDialog.vue"
		).read_text()
		contact_sources = (
			ui_root / "features/settings/components/ContactSourcesCard.vue"
		).read_text()
		self.assertIn("<ChannelSelect", inbox)
		self.assertIn("<TemplateSelect", inbox)
		self.assertIn("<TemplateSelect", template_send)
		self.assertIn("<LinkField", contact_sources)
		self.assertIn("@/components/form/LinkField.vue", contact_sources)

	def test_ai_summary_settings_require_a_frappe_tools_action(self):
		with self.assertRaises(frappe.ValidationError):
			save_ai_summary_settings(enabled=1, action="Missing I2A Action")

		settings = save_ai_summary_settings(
			enabled=0,
			action="",
			batch_size=0,
			max_media_mb=99,
		)
		self.assertFalse(settings["ai_summary"]["enabled"])
		self.assertEqual(settings["ai_summary"]["batch_size"], 100)
		self.assertEqual(settings["ai_summary"]["max_media_mb"], 50)

	def test_ai_activation_boundary_is_created_once_per_enabled_period(self):
		action = frappe.db.get_value("I2A Action", {"enabled": 1}, "name")
		if not action:
			self.skipTest("No enabled I2A Action is available on the local test site")
		with patch(
			"frappe_whatsapp_core.frontend_api._i2a_schema_available",
			return_value=True,
		):
			save_ai_summary_settings(enabled=0, action="")
			first = save_ai_summary_settings(enabled=1, action=action)["ai_summary"]
			second = save_ai_summary_settings(enabled=1, action=action)["ai_summary"]
			self.assertTrue(first["enabled_from"])
			self.assertEqual(first["enabled_from"], second["enabled_from"])
			disabled = save_ai_summary_settings(enabled=0, action="")["ai_summary"]
			self.assertFalse(disabled["enabled_from"])

	def test_i2a_schema_probe_short_circuits_when_frappe_tools_is_absent(self):
		with (
			patch(
				"frappe_whatsapp_core.frontend_api.frappe.get_installed_apps",
				return_value=["frappe", "frappe_whatsapp_core"],
			),
			patch("frappe_whatsapp_core.frontend_api.frappe.db.exists") as exists,
		):
			self.assertFalse(_i2a_schema_available())
		exists.assert_not_called()

		with (
			patch("frappe_whatsapp_core.frontend_api._i2a_schema_available", return_value=False),
			self.assertRaisesRegex(
				frappe.ValidationError,
				"Install Frappe Tools before enabling AI summaries",
			),
		):
			save_ai_summary_settings(enabled=1, action="Optional Action")

	@patch("frappe_whatsapp_core.frontend_api.call_management")
	def test_hub_account_discovery_returns_only_integration_options(self, call_management):
		call_management.return_value = {
			"accounts": [{"name": "Primary Account", "verified_name": "Essdee"}]
		}
		self.assertEqual(discover_hub_accounts()[0]["name"], "Primary Account")
		call_management.assert_called_once_with(
			"frappe_whatsapp_hub.frappe_whatsapp_hub.api.onboarding.list_site_accounts"
		)

	def test_hub_account_mappings_reject_duplicates_and_normalize_default(self):
		channel = get_or_create_channel(f"SETTINGS-{self.suffix}", f"WABA-{self.suffix}")
		rows = _validated_hub_account_mappings([
			{"channel": channel.name, "account_name": "Primary Account", "is_default": 0}
		])
		self.assertTrue(rows[0]["is_default"])
		with self.assertRaises(frappe.ValidationError):
			_validated_hub_account_mappings([
				{"channel": channel.name, "account_name": "Primary Account"},
				{"channel": channel.name, "account_name": "Secondary Account"},
			])

	def test_contact_source_configuration_uses_real_doctype_fields(self):
		doctypes = contact_source_doctypes(search="User")
		self.assertIn("User", {row.name for row in doctypes})
		fields = contact_source_fields("User")
		self.assertIn("mobile_no", {row["value"] for row in fields["phone_fields"]})
		self.assertIn("first_name", {row["value"] for row in fields["filter_fields"]})
		self.assertNotIn("Password", {row["fieldtype"] for row in fields["filter_fields"]})
		source = save_contact_source({
			"source_key": f"ui.user.{self.suffix}",
			"display_name": "UI Users",
			"source_doctype": "User",
			"phone_field": "mobile_no",
			"display_name_field": "full_name",
			"enabled": 1,
			"auto_resolve": 1,
			"priority": 50,
		})
		self.assertEqual(source.source_doctype, "User")
		self.assertIn(source.name, {row.name for row in settings_workspace()["contact_sources"]})

	def test_router_preserves_both_public_whatsapp_entry_points(self):
		router = (
			Path(__file__).resolve().parents[2] / "core_ui" / "src" / "router.js"
		).read_text()
		self.assertIn("window.location.pathname.startsWith('/whatsapp_core')", router)
		self.assertIn(": '/whatsapp/'", router)

	def test_realtime_uses_the_dev_socketio_port(self):
		realtime = (
			Path(__file__).resolve().parents[2]
			/ "core_ui"
			/ "src"
			/ "services"
			/ "realtime.js"
		).read_text()
		self.assertIn("boot.developer_mode && boot.socketio_port", realtime)
		self.assertIn("origin.port = String(boot.socketio_port)", realtime)

		from frappe_whatsapp_core.www.whatsapp_core import get_context

		context = frappe._dict()
		with patch.object(frappe.sessions, "get_csrf_token", return_value="csrf-test"):
			get_context(context)
		self.assertEqual(context.boot["socketio_port"], frappe.conf.get("socketio_port") or 9000)
