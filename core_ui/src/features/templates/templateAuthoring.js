const DEFAULT_COMPONENTS = [{ type: 'BODY', text: '' }]

export function parseTemplateComponents(value, { allowEmpty = false } = {}) {
	let parsed = value
	try {
		if (typeof value === 'string') parsed = JSON.parse(value || '[]')
	} catch (_error) {
		throw new Error('Components must contain valid JSON.')
	}
	if (!Array.isArray(parsed) || (!allowEmpty && !parsed.length)) {
		throw new Error('Components must be a non-empty JSON array.')
	}
	for (const component of parsed) {
		if (!component || typeof component !== 'object' || Array.isArray(component)) {
			throw new Error('Every component must be a JSON object.')
		}
		const type = String(component.type || '')
			.trim()
			.toUpperCase()
		if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(type)) {
			throw new Error('Every component requires a valid Meta type.')
		}
		component.type = type
	}
	if (!parsed.some((component) => component.type === 'BODY')) {
		throw new Error('A BODY component is required.')
	}
	return parsed
}

export function templateForm(row = {}, accounts = []) {
	const componentSource = Object.prototype.hasOwnProperty.call(row, 'components')
		? row.components
		: DEFAULT_COMPONENTS
	const components = parseTemplateComponents(componentSource)
	return {
		account_name: row.account_name || accounts[0]?.account_name || '',
		template_name: row.template_name || '',
		language_code: row.language_code || 'en',
		category: row.category || 'UTILITY',
		parameter_format: row.parameter_format || 'POSITIONAL',
		message_send_ttl_seconds: row.message_send_ttl_seconds || '',
		components_json: JSON.stringify(components, null, 2),
	}
}

export function templateRequest(form, { templateKey = null, submit = false } = {}) {
	const accountName = String(form.account_name || '').trim()
	const templateName = String(form.template_name || '').trim()
	const languageCode = String(form.language_code || '').trim()
	const category = String(form.category || '')
		.trim()
		.toUpperCase()
	const parameterFormat = String(form.parameter_format || 'POSITIONAL')
		.trim()
		.toUpperCase()
	if (!accountName || !templateName || !languageCode) {
		throw new Error('Account, template name, and language are required.')
	}
	if (!/^[a-z0-9_]{1,512}$/.test(templateName)) {
		throw new Error('Template name must use lowercase letters, numbers, and underscores.')
	}
	if (!['MARKETING', 'UTILITY', 'AUTHENTICATION'].includes(category)) {
		throw new Error('Template category is invalid.')
	}
	if (!['POSITIONAL', 'NAMED'].includes(parameterFormat)) {
		throw new Error('Parameter format is invalid.')
	}
	const ttlValue = String(form.message_send_ttl_seconds || '').trim()
	if (ttlValue && (!/^\d+$/.test(ttlValue) || Number(ttlValue) < 1)) {
		throw new Error('Message send TTL must be a positive number of seconds.')
	}
	const template = {
		account_name: accountName,
		template_name: templateName,
		language_code: languageCode,
		category,
		parameter_format: parameterFormat,
		components: parseTemplateComponents(form.components_json),
	}
	if (ttlValue) template.message_send_ttl_seconds = Number(ttlValue)
	return { template_key: templateKey, template, submit }
}

export function formatTemplateComponents(value) {
	return JSON.stringify(parseTemplateComponents(value), null, 2)
}
