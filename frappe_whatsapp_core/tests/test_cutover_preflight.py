from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from frappe_whatsapp_core import cutover


class _Settings:
	enabled = 1
	outbound_enabled = 1
	hub_url = "https://hub.example.test"
	accounts = [SimpleNamespace(
		channel="CHANNEL-1",
		account_name="ACCOUNT-1",
		is_default=1,
		template_service_user="whatsapp-core-template-service@example.test",
	)]

	def get_password(self, fieldname, raise_exception=False):
		return f"configured-{fieldname}"


class TestProductionPreflight(TestCase):
	@patch(
		"frappe_whatsapp_core.cutover._identity_schema_status",
		return_value=(True, "Identity schema ready"),
	)
	@patch("frappe_whatsapp_core.cutover.is_dedicated_transport_user", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.get_all")
	@patch("frappe_whatsapp_core.cutover.frappe.db.get_value")
	@patch("frappe_whatsapp_core.cutover.frappe.db.exists", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.get_single", return_value=_Settings())
	def test_ready_report_is_read_only_and_secret_free(
		self, _get_single, _exists, get_value, get_all, _dedicated, _schema
	):
		get_value.return_value = {"enabled": 1, "phone_number_id": "PHONE-1"}
		get_all.side_effect = lambda _doctype, filters, **_kwargs: [
			f"{filters['role'].lower().replace(' ', '-')}@example.test"
		]

		result = cutover.production_preflight()

		self.assertEqual(result["product"]["version"], "1.0.0")
		self.assertEqual(result["product"]["transport_contract_version"], 3)
		self.assertTrue(result["ready"])
		self.assertEqual(result["failed"], 0)
		self.assertTrue(result["live_meta_canary_required"])
		self.assertNotIn("configured-api_secret", str(result))
		self.assertEqual(get_all.call_count, 3)

	@patch(
		"frappe_whatsapp_core.cutover._identity_schema_status",
		return_value=(True, "Identity schema ready"),
	)
	@patch("frappe_whatsapp_core.cutover.is_dedicated_transport_user", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.get_all")
	@patch("frappe_whatsapp_core.cutover.frappe.db.get_value")
	@patch("frappe_whatsapp_core.cutover.frappe.db.exists", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.get_single")
	def test_ready_report_uses_fixed_hub_gateway(
		self, get_single, _exists, get_value, get_all, _dedicated, _schema
	):
		get_single.return_value = _Settings()
		get_value.return_value = {"enabled": 1, "phone_number_id": "PHONE-1"}
		get_all.side_effect = lambda _doctype, filters, **_kwargs: [
			f"{filters['role'].lower().replace(' ', '-')}@example.test"
		]

		result = cutover.production_preflight()

		self.assertTrue(result["ready"])
		data_plane = next(row for row in result["checks"] if row["key"] == "data_plane")
		self.assertIn("Hub-managed Frappe gateway", data_plane["detail"])

	@patch(
		"frappe_whatsapp_core.cutover._identity_schema_status",
		return_value=(False, "Run migrate: alias table missing"),
	)
	@patch("frappe_whatsapp_core.cutover.is_dedicated_transport_user", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.get_all")
	@patch("frappe_whatsapp_core.cutover.frappe.db.get_value")
	@patch("frappe_whatsapp_core.cutover.frappe.db.exists", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.get_single", return_value=_Settings())
	def test_report_fails_closed_for_missing_identity_schema(
		self, _get_single, _exists, get_value, get_all, _dedicated, _schema
	):
		get_value.return_value = {"enabled": 1, "phone_number_id": "PHONE-1"}
		get_all.side_effect = lambda _doctype, filters, **_kwargs: [
			f"{filters['role'].lower().replace(' ', '-')}@example.test"
		]

		result = cutover.production_preflight()

		self.assertFalse(result["ready"])
		failed = {row["key"] for row in result["checks"] if not row["ready"]}
		self.assertEqual(failed, {"identity_schema"})

	@patch(
		"frappe_whatsapp_core.cutover._identity_schema_status",
		return_value=(True, "Identity schema ready"),
	)
	@patch("frappe_whatsapp_core.cutover.is_dedicated_transport_user", return_value=False)
	@patch("frappe_whatsapp_core.cutover.frappe.get_all", return_value=["unsafe@example.test"])
	@patch("frappe_whatsapp_core.cutover.frappe.db.get_value", return_value={"enabled": 0})
	@patch("frappe_whatsapp_core.cutover.frappe.db.exists", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.get_single")
	def test_report_fails_closed_for_bad_channels_credentials_and_identities(
		self, get_single, _exists, _get_value, _get_all, _dedicated, _schema
	):
		settings = _Settings()
		settings.get_password = lambda *_args, **_kwargs: ""
		get_single.return_value = settings

		result = cutover.production_preflight()

		self.assertFalse(result["ready"])
		failed = {row["key"] for row in result["checks"] if not row["ready"]}
		self.assertIn("hub_credentials", failed)
		self.assertIn("channels", failed)
		self.assertIn("service_identity:ingress", failed)
		self.assertIn("service_identity:template", failed)
		self.assertIn("service_identity:flow", failed)

	def test_identity_aliases_are_deleted_before_identities(self):
		aliases = cutover.CORE_RUNTIME_DOCTYPES.index("WhatsApp Core Identity Alias")
		identities = cutover.CORE_RUNTIME_DOCTYPES.index("WhatsApp Core Identity")
		self.assertLess(aliases, identities)

	@patch("frappe_whatsapp_core.cutover._has_exact_unique_index", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.db.get_table_columns")
	@patch("frappe_whatsapp_core.cutover.frappe.db.table_exists", return_value=True)
	def test_identity_schema_checks_physical_fields(self, _table_exists, columns, unique):
		columns.side_effect = [
			["name", "identifier_type", "identity_scope"],
			["name", "alias_key", "identity", "alias_type", "identity_scope", "alias_value"],
			["name", "provider_template_id"],
			[
				"name",
				"account_name",
				"channel",
				"components",
				"correct_category",
				"message_send_ttl_seconds",
				"parameter_format",
				"status_reason",
				"template_source",
			],
			["name", "template_service_user"],
		]
		self.assertEqual(
			cutover._identity_schema_status(),
			(True, "Identity, template, alias, and provider status schema are ready"),
		)
		unique.assert_called_once_with("WhatsApp Core Identity Alias", "alias_key")

	@patch("frappe_whatsapp_core.cutover._has_exact_unique_index", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.db.get_table_columns")
	@patch("frappe_whatsapp_core.cutover.frappe.db.table_exists", return_value=True)
	def test_identity_schema_fails_closed_without_provider_template_id(
		self, _table_exists, columns, _unique
	):
		columns.side_effect = [
			["name", "identifier_type", "identity_scope"],
			["name", "alias_key", "identity", "alias_type", "identity_scope", "alias_value"],
			["name", "content"],
			["name"],
			["name"],
		]
		self.assertEqual(
			cutover._identity_schema_status(),
			(False, "Run migrate: WhatsApp Core Message is missing provider_template_id"),
		)

	@patch("frappe_whatsapp_core.cutover._has_exact_unique_index", return_value=True)
	@patch("frappe_whatsapp_core.cutover.frappe.db.get_table_columns")
	@patch("frappe_whatsapp_core.cutover.frappe.db.table_exists", return_value=True)
	def test_identity_schema_fails_closed_without_template_authoring_fields(
		self, _table_exists, columns, _unique
	):
		columns.side_effect = [
			["name", "identifier_type", "identity_scope"],
			["name", "alias_key", "identity", "alias_type", "identity_scope", "alias_value"],
			["name", "provider_template_id"],
			["name", "account_name", "channel", "components"],
			["name"],
		]
		ready, detail = cutover._identity_schema_status()
		self.assertFalse(ready)
		self.assertIn("message_send_ttl_seconds", detail)
		self.assertIn("parameter_format", detail)
		self.assertIn("status_reason", detail)

	@patch("frappe_whatsapp_core.cutover.frappe.db.sql")
	def test_exact_unique_index_supports_mariadb_and_postgres(self, sql):
		with patch.object(cutover.frappe.db, "db_type", "mariadb"):
			sql.return_value = [{"index_name": "uniq_alias", "columns": "alias_key"}]
			self.assertTrue(cutover._has_exact_unique_index("WhatsApp Core Identity Alias", "alias_key"))

		with patch.object(cutover.frappe.db, "db_type", "postgres"):
			sql.return_value = [{"index_name": "uniq_alias", "columns": ["alias_key"]}]
			self.assertTrue(cutover._has_exact_unique_index("WhatsApp Core Identity Alias", "alias_key"))
			query = sql.call_args.args[0]
			self.assertIn("idx.indisvalid", query)
			self.assertIn("idx.indisready", query)
