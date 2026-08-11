const HIDDEN_KEYS = new Set([
	'flow_token',
	'screen',
	'_core_action',
	'_action',
	'_method',
	'_endpoint',
])

export function parseFlowValue(value) {
	if (value === null || value === undefined || value === '') return null
	if (typeof value === 'object') return value
	if (typeof value !== 'string') return value
	try {
		return JSON.parse(value)
	} catch {
		return value
	}
}

export function flowReplyFromContent(content) {
	const parsed = parseFlowValue(content) || {}
	const interactive = parsed.interactive || parsed.payload?.interactive || {}
	const reply = interactive.nfm_reply || parsed.nfm_reply || {}
	return {
		body: reply.body || '',
		name: reply.name || '',
		response: parseFlowValue(reply.response_json),
	}
}

export function humanizeFlowKey(value) {
	return String(value || '')
		.replace(/^screen[_-]?\d*[_-]?/i, '')
		.replace(/^form[_-]?/i, '')
		.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
		.replace(/[_-]+/g, ' ')
		.replace(/\s+/g, ' ')
		.trim()
		.replace(/^./, (character) => character.toUpperCase())
}

function displayValue(value) {
	if (value === true) return 'Yes'
	if (value === false) return 'No'
	if (value === null || value === undefined || value === '') return '—'
	if (Array.isArray(value)) return value.map(displayValue).join(', ')
	return String(value)
}

function flatten(value, prefix = '', depth = 0) {
	const parsed = parseFlowValue(value)
	if (!parsed || typeof parsed !== 'object') {
		return prefix
			? [{ key: prefix, label: humanizeFlowKey(prefix), value: displayValue(parsed) }]
			: []
	}
	if (Array.isArray(parsed)) {
		return prefix
			? [{ key: prefix, label: humanizeFlowKey(prefix), value: displayValue(parsed) }]
			: []
	}
	return Object.entries(parsed).flatMap(([key, item]) => {
		if (HIDDEN_KEYS.has(key) || key.startsWith('__')) return []
		const path = prefix ? `${prefix}.${key}` : key
		if (item && typeof item === 'object' && !Array.isArray(item) && depth < 2) {
			return flatten(item, path, depth + 1)
		}
		return [{ key: path, label: humanizeFlowKey(key), value: displayValue(item) }]
	})
}

export function flowResponseFields(response) {
	return flatten(response).filter((field) => field.value !== '—')
}
