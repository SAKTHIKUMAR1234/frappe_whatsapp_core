import { call } from '@/services/frappe'

const FLOW_API = 'frappe_whatsapp_core.flow_api'

export function getFlow(flowName) {
	return call(`${FLOW_API}.get_builder`, {
		flow_name: flowName,
	})
}

export function saveFlowDraft(flowName, graph) {
	return call(`${FLOW_API}.save_draft`, {
		flow_name: flowName,
		graph,
	})
}

export function publishFlow(flowName) {
	return call(`${FLOW_API}.publish`, {
		flow_name: flowName,
	})
}
