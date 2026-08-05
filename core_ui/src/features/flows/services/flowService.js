import { call } from '@/services/frappe'

const API = 'frappe_whatsapp_core.meta_flows'

export const flowWorkspace = (accountName = '') =>
	call(`${API}.flow_workspace`, { account_name: accountName })

export const getFlow = (accountName, flowId) =>
	call(`${API}.get_flow`, { account_name: accountName, flow_id: flowId })

export const createFlow = (values) => call(`${API}.create_flow`, values)

export const updateFlow = (values) => call(`${API}.update_flow`, values)

export const uploadFlowJson = (accountName, flowId, flowJson) =>
	call(`${API}.upload_flow_json`, {
		account_name: accountName,
		flow_id: flowId,
		flow_json: flowJson,
	})

export const publishFlow = (accountName, flowId) =>
	call(`${API}.publish_flow`, { account_name: accountName, flow_id: flowId })

export const deprecateFlow = (accountName, flowId) =>
	call(`${API}.deprecate_flow`, { account_name: accountName, flow_id: flowId })

export const deleteFlow = (accountName, flowId) =>
	call(`${API}.delete_flow`, { account_name: accountName, flow_id: flowId })

export const migrateFlows = (accountName, sourceWabaId, sourceFlowNames = []) =>
	call(`${API}.migrate_flows`, {
		account_name: accountName,
		source_waba_id: sourceWabaId,
		source_flow_names: sourceFlowNames,
	})

export const getBusinessPublicKey = (accountName) =>
	call(`${API}.get_business_public_key`, { account_name: accountName })

export const setBusinessPublicKey = (accountName, businessPublicKey) =>
	call(`${API}.set_business_public_key`, {
		account_name: accountName,
		business_public_key: businessPublicKey,
	})
