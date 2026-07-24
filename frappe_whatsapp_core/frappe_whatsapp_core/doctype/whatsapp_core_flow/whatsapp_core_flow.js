frappe.ui.form.on("WhatsApp Core Flow", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Open Flow Builder"), () => {
				frappe.set_route("whatsapp-flow-builder", frm.doc.name);
			});
		}
	},
});
