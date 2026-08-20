(() => {
	function default_transport_email() {
		const site = String(frappe.boot?.sitename || window.location.hostname || "")
			.trim()
			.toLowerCase();
		return site ? `whatsapp-core-service@${site}` : "";
	}

	function show_transport_credentials(credentials) {
		const escape = frappe.utils.escape_html;
		const account_list = (credentials.allowed_accounts || [])
			.map((account) => `<li><code>${escape(account)}</code></li>`)
			.join("");
		const credential_text = [
			`Service user: ${credentials.user}`,
			`API key: ${credentials.api_key}`,
			`API secret: ${credentials.api_secret}`,
		].join("\n");
		const dialog = new frappe.ui.Dialog({
			title: __("Integration credential — copy now"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "credential_details",
				},
			],
			primary_action_label: __("Copy credentials"),
			primary_action: () => {
				frappe.utils.copy_to_clipboard(credential_text);
				frappe.show_alert({
					message: __("Integration credentials copied"),
					indicator: "green",
				});
			},
		});
		dialog.fields_dict.credential_details.$wrapper.html(`
		<div class="alert alert-warning">
			${__("The API secret is shown only once. Store it securely in the matching Hub Connected Site before closing this dialog.")}
		</div>
		<p><strong>${__("Service user")}</strong><br><code>${escape(credentials.user)}</code></p>
		<p><strong>${__("API key")}</strong><br><code>${escape(credentials.api_key)}</code></p>
		<p><strong>${__("API secret")}</strong><br><code>${escape(credentials.api_secret)}</code></p>
		<p><strong>${__("Allowed Hub accounts")}</strong></p>
		<ul>${account_list}</ul>
	`);
		dialog.show();
	}

	function provision_transport_credentials(frm) {
		const mapped_accounts = (frm.doc.accounts || []).filter(
			(row) => row.channel && row.account_name,
		);
		if (!mapped_accounts.length) {
			frappe.msgprint({
				title: __("Map a Hub account first"),
				indicator: "orange",
				message: __(
					"Add and save at least one Channel Routing row before generating the unified integration credential.",
				),
			});
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Generate Integration Credential"),
			fields: [
				{
					fieldname: "service_email",
					fieldtype: "Data",
					label: __("Dedicated service email"),
					options: "Email",
					default: default_transport_email(),
					reqd: 1,
					description: __(
						"A service-only Website User will be created. Do not enter a human or Desk user.",
					),
				},
				{
					fieldname: "rotate",
					fieldtype: "Check",
					label: __("Rotate existing credential"),
					default: 0,
					description: __(
						"Enable only when replacing this service user's existing key and secret.",
					),
				},
			],
			primary_action_label: __("Generate once"),
			primary_action: async (values) => {
				if (frm.is_dirty()) {
					await frm.save();
				}
				dialog.disable_primary_action();
				try {
					const response = await frappe.call({
						method: "frappe_whatsapp_core.frontend_api.provision_transport_credentials",
						args: {
							user_email: values.service_email,
							rotate: values.rotate ? 1 : 0,
							capability: "all",
						},
						freeze: true,
						freeze_message: __(
							"Generating a least-privilege integration credential...",
						),
					});
					dialog.hide();
					show_transport_credentials(response.message);
					frm.reload_doc();
				} finally {
					dialog.enable_primary_action();
				}
			},
		});
		dialog.show();
	}

	frappe.ui.form.on("WhatsApp Core Settings", {
		refresh(frm) {
			if (!frappe.user.has_role("System Manager")) return;
			frm.add_custom_button(
				__("Generate Integration Credential"),
				() => provision_transport_credentials(frm),
				__("Security"),
			);
		},
	});
})();
