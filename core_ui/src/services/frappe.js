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

export async function login(usr, pwd) {
	const { data } = await client.post('/api/method/login', new URLSearchParams({ usr, pwd }), {
		headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
	})
	return data
}

export async function logout() {
	await client.get('/api/method/logout')
}

export default client
