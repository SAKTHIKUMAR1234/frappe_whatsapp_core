import axios from 'axios'

const client = axios.create({
	headers: {
		Accept: 'application/json',
		'X-Frappe-CSRF-Token': window.csrf_token || '',
	},
})

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
	const exception = payload.exception
	if (exception) return String(exception).split(':').at(-1).trim()
	return payload.message || error?.message || fallback
}

export default client
