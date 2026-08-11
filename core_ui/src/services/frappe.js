import axios from 'axios'

const client = axios.create({
	headers: {
		Accept: 'application/json',
	},
})

const AUTH_EXPIRED_EVENT = 'whatsapp-core:auth-expired'
const API_FAILURE_EVENT = 'whatsapp-core:api-failure'
const CSRF_STORAGE_KEY = 'whatsapp-core:csrf-token'

function setCsrfToken(token) {
	if (!token) return
	window.csrf_token = token
	if (window.frappe) window.frappe.csrf_token = token
	try {
		window.localStorage.setItem(CSRF_STORAGE_KEY, token)
	} catch {
		// Storage may be disabled; the in-memory token still protects this tab.
	}
}

function currentCsrfToken() {
	let stored = ''
	try {
		stored = window.localStorage.getItem(CSRF_STORAGE_KEY) || ''
	} catch {
		// Storage may be disabled; use the token injected by Frappe.
	}
	return window.csrf_token || window.frappe?.csrf_token || stored
}

window.addEventListener('storage', (event) => {
	if (event.key === CSRF_STORAGE_KEY && event.newValue) setCsrfToken(event.newValue)
})

client.interceptors.request.use((config) => {
	const token = currentCsrfToken()
	if (token) config.headers['X-Frappe-CSRF-Token'] = token
	return config
})

client.interceptors.response.use(
	(response) => {
		setCsrfToken(response.headers?.['x-frappe-csrf-token'])
		return response
	},
	(error) => {
		const status = error?.response?.status
		if (status === 401 || (status === 403 && /login/i.test(errorMessage(error)))) {
			window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, { detail: error }))
		}
		if (!error?.response) {
			window.dispatchEvent(
				new CustomEvent(API_FAILURE_EVENT, { detail: errorDetails(error) }),
			)
		}
		return Promise.reject(error)
	},
)

export async function call(method, args = {}) {
	const { data } = await client.post(`/api/method/${method}`, args)
	return data.message
}

export async function uploadFile(file, isPrivate = true) {
	const form = new FormData()
	form.append('file', file)
	form.append('is_private', isPrivate ? '1' : '0')
	const { data } = await client.post('/api/method/upload_file', form, {
		headers: { 'Content-Type': 'multipart/form-data' },
	})
	return data.message
}

export async function login(usr, pwd) {
	const { data } = await client.post('/api/method/login', new URLSearchParams({ usr, pwd }), {
		headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
	})
	return data
}

export async function logout() {
	await client.get('/api/method/logout')
}

export function errorMessage(error, fallback = 'Unexpected server error') {
	const payload = error?.response?.data || {}
	if (payload._server_messages) {
		try {
			const messages = JSON.parse(payload._server_messages)
			const first = messages.length ? JSON.parse(messages[0]) : null
			if (first?.message) return first.message
		} catch {
			// Fall through to the standard Frappe/HTTP error fields.
		}
	}
	if (payload.message && typeof payload.message === 'string')
		return cleanMessage(payload.message)

	const exception = payload.exception
	if (exception) return cleanMessage(String(exception).split(':').at(-1).trim())

	if (!error?.response) {
		if (error?.code === 'ERR_NETWORK')
			return 'Cannot reach the server. Check your connection and try again.'
		if (error?.code === 'ECONNABORTED') return 'The request took too long. Please try again.'
	}

	const status = error?.response?.status
	const statusMessages = {
		400: 'The request contains invalid information.',
		401: 'Your session has expired. Sign in again to continue.',
		403: 'You do not have permission to perform this action.',
		404: 'The requested record could not be found.',
		409: 'This record changed in another session. Reload it and try again.',
		413: 'The selected file is too large.',
		417: 'The server rejected this operation. Review the entered information and try again.',
		429: 'Too many requests were sent. Wait a moment and try again.',
		502: 'The integration service is temporarily unavailable.',
		503: 'The service is temporarily unavailable.',
		504: 'The integration service did not respond in time.',
	}
	return statusMessages[status] || cleanMessage(error?.message) || fallback
}

export function friendlyMessage(value, fallback = '') {
	const message = cleanMessage(value)
	if (!message) return fallback
	if (/131215|not eligible to access groups apis/i.test(message))
		return (
			'Meta Groups is unavailable for this phone number. Groups currently requires ' +
			'an eligible Official Business Account (OBA) phone number.'
		)
	if (/session has expired|error validating access token/i.test(message))
		return 'Meta access token expired. Update the account credential in Integration, then retry.'
	if (/Meta Graph API request failed \(401\)|OAuthException/i.test(message))
		return 'Meta authentication failed. Update the account credential in Integration, then retry.'
	return message
}

export function errorDetails(error, fallback) {
	const response = error?.response
	return {
		message: errorMessage(error, fallback),
		status: response?.status || 0,
		requestId:
			response?.headers?.['x-request-id'] ||
			response?.data?.request_id ||
			response?.data?._request_id ||
			'',
		retryable: !response || [408, 409, 425, 429, 502, 503, 504].includes(response.status),
	}
}

function cleanMessage(value) {
	if (!value) return ''
	const container = document.createElement('div')
	container.innerHTML = String(value)
	return (container.textContent || container.innerText || '').replace(/\s+/g, ' ').trim()
}

export function onAuthExpired(callback) {
	window.addEventListener(AUTH_EXPIRED_EVENT, callback)
	return () => window.removeEventListener(AUTH_EXPIRED_EVENT, callback)
}

export function onApiFailure(callback) {
	window.addEventListener(API_FAILURE_EVENT, callback)
	return () => window.removeEventListener(API_FAILURE_EVENT, callback)
}

export default client
