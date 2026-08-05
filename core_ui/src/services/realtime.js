import { io } from 'socket.io-client'

let socket = null
let activeSite = null

function connection(site) {
	if (socket && activeSite === site) return socket
	if (socket) socket.disconnect()

	activeSite = site
	socket = io(`${window.location.origin}/${site}`, {
		secure: window.location.protocol === 'https:',
		withCredentials: true,
		reconnection: true,
		reconnectionAttempts: 10,
		reconnectionDelay: 750,
		timeout: 8000,
	})
	return socket
}

export function subscribe(site, event, callback) {
	if (!site) return () => {}
	const client = connection(site)
	client.on(event, callback)
	return () => client.off(event, callback)
}
