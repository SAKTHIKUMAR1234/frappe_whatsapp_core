frappe.pages["whatsapp-flow-builder"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("WhatsApp Flow Builder"),
		single_column: true,
	});
};

frappe.pages["whatsapp-flow-builder"].on_page_show = function (wrapper) {
	const route = frappe.get_route();
	const flow_name = route[1];
	const $parent = $(wrapper).find(".layout-main-section");
	$parent.empty();

	if (!flow_name) {
		frappe.prompt(
			[
				{
					fieldname: "flow",
					fieldtype: "Link",
					options: "WhatsApp Core Flow",
					label: __("Select Flow"),
					reqd: 1,
				},
			],
			({ flow }) => frappe.set_route("whatsapp-flow-builder", flow),
			__("Open Flow")
		);
		return;
	}

	frappe.require("whatsapp_flow_builder.bundle.js").then(() => {
		frappe.whatsapp_flow_builder = new frappe.ui.WhatsAppFlowBuilder({
			wrapper: $parent,
			page: wrapper.page,
			flow_name,
		});
	});
};
