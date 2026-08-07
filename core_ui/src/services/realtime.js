import { io } from 'socket.io-client'

let socket = null
let activeSite = null

export function socketEndpoint(site, boot = window.core_boot || {}) {
	const origin = new URL(window.location.origin)
	if (boot.developer_mode && boot.socketio_port) {
		origin.port = String(boot.socketio_port)
	}
	return `${origin.origin}/${site}`
}

function connection(site) {
	if (socket && activeSite === site) return socket
	if (socket) socket.disconnect()

	activeSite = site
	socket = io(socketEndpoint(site), {
		secure: window.location.protocol === 'https:',
		withCredentials: true,
		reconnection: true,
		reconnectionAttempts: Infinity,
		reconnectionDelay: 750,
		reconnectionDelayMax: 8000,
		randomizationFactor: 0.4,
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

export function subscribeConnection(site, callback) {
	if (!site) return () => {}
	const client = connection(site)
	const connected = () => callback('connected')
	const disconnected = () => callback('disconnected')
	const failed = () => callback('reconnecting')
	client.on('connect', connected)
	client.on('disconnect', disconnected)
	client.on('connect_error', failed)
	callback(client.connected ? 'connected' : 'connecting')
	return () => {
		client.off('connect', connected)
		client.off('disconnect', disconnected)
		client.off('connect_error', failed)
	}
}
