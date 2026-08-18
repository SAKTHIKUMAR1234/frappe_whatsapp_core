const POSITIVE = new Set(['granted', 'active', 'allowed', 'approved', 'enabled'])
const NEGATIVE = new Set([
	'denied',
	'declined',
	'disabled',
	'expired',
	'not_granted',
	'not_allowed',
])

function firstObject(value) {
	if (Array.isArray(value)) return value.find((item) => item && typeof item === 'object') || {}
	return value && typeof value === 'object' ? value : {}
}

function permissionObject(response) {
	let value = firstObject(response?.data ?? response)
	for (const key of ['call_permission', 'call_permissions', 'permission_details']) {
		if (value?.[key] && typeof value[key] === 'object') value = firstObject(value[key])
	}
	return value
}

function statusValue(value) {
	for (const key of ['call_permission_status', 'permission_status', 'permission', 'status']) {
		const candidate = value?.[key]
		if (candidate && typeof candidate === 'object') {
			const nested = statusValue(candidate)
			if (nested) return nested
		} else if (candidate !== undefined && candidate !== null && String(candidate).trim()) {
			return String(candidate).trim()
		}
	}
	if (value?.can_call === true || value?.allowed === true) return 'granted'
	if (value?.can_call === false || value?.allowed === false) return 'denied'
	return 'unknown'
}

function expirationValue(value) {
	for (const key of ['expiration_time', 'expires_at', 'expiration', 'expires']) {
		if (value?.[key]) return value[key]
	}
	for (const key of [
		'call_permission',
		'call_permissions',
		'permission_details',
		'call_permission_status',
		'permission_status',
		'permission',
	]) {
		const candidate = firstObject(value?.[key])
		const expiresAt = Object.keys(candidate).length ? expirationValue(candidate) : ''
		if (expiresAt) return expiresAt
	}
	return ''
}

export function normalizeCallPermission(response) {
	const value = permissionObject(response)
	const status = statusValue(value).toLowerCase().replaceAll(' ', '_')
	const allowed = POSITIVE.has(status)
	const label = allowed
		? 'Allowed'
		: NEGATIVE.has(status)
			? status === 'expired'
				? 'Expired'
				: 'Not allowed'
			: status === 'pending'
				? 'Pending approval'
				: 'Unknown'
	return {
		status,
		label,
		allowed,
		expiresAt: expirationValue(value),
	}
}
