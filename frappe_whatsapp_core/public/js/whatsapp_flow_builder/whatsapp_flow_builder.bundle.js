import { createApp } from "vue";
import FlowBuilder from "./FlowBuilder.vue";

class WhatsAppFlowBuilder {
	constructor({ wrapper, page, flow_name }) {
		this.wrapper = wrapper;
		this.page = page;
		this.flow_name = flow_name;
		this.page.set_title(__("Flow Builder: {0}", [flow_name]));
		this.app = createApp(FlowBuilder, { flowName: flow_name, page });
		SetVueGlobals(this.app);
		this.instance = this.app.mount($(wrapper).get(0));
	}
}

frappe.provide("frappe.ui");
frappe.ui.WhatsAppFlowBuilder = WhatsAppFlowBuilder;
export default WhatsAppFlowBuilder;
