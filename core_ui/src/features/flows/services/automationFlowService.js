import { call } from '@/services/frappe'

const FLOW_API = 'frappe_whatsapp_core.flow_api'

export const listAutomationFlows = () => call('frappe_whatsapp_core.frontend_api.list_flows')

export const createAutomationFlow = (values) =>
	call('frappe_whatsapp_core.frontend_api.create_starter_flow', values)

export const getAutomationFlow = (flowName) =>
	call(`${FLOW_API}.get_builder`, { flow_name: flowName })

export const saveAutomationFlowDraft = (flowName, graph) =>
	call(`${FLOW_API}.save_draft`, { flow_name: flowName, graph })

export const publishAutomationFlow = (flowName) =>
	call(`${FLOW_API}.publish`, { flow_name: flowName })

export const requestAutomationFlowApproval = (flowName) =>
	call(`${FLOW_API}.request_approval`, { flow_name: flowName })
