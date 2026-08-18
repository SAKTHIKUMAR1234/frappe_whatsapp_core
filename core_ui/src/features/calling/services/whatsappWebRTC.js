const AUDIO_CONSTRAINTS = {
	audio: {
		echoCancellation: true,
		noiseSuppression: true,
		autoGainControl: true,
		channelCount: 1,
	},
	video: false,
}

export const TERMINAL_CALL_STATES = new Set([
	'terminate',
	'terminated',
	'ended',
	'rejected',
	'failed',
	'missed',
])

export function normalizedCallStatus(value) {
	return String(value || '')
		.trim()
		.toLowerCase()
}

export function parseCallSession(value) {
	if (!value) return null
	if (typeof value === 'string') {
		try {
			value = JSON.parse(value)
		} catch {
			return null
		}
	}
	if (!value || typeof value !== 'object') return null
	const sdpType = String(value.sdp_type || '').toLowerCase()
	const sdp = String(value.sdp || '')
	return ['offer', 'answer'].includes(sdpType) && sdp ? { type: sdpType, sdp } : null
}

export function isIncomingRinging(call) {
	const session = parseCallSession(call?.session)
	return (
		String(call?.direction || '').toLowerCase() === 'inbound' &&
		['connect', 'ringing', 'received'].includes(normalizedCallStatus(call?.status)) &&
		session?.type === 'offer'
	)
}

function waitForIceGathering(peer, timeout = 8000) {
	if (peer.iceGatheringState === 'complete') return Promise.resolve()
	return new Promise((resolve) => {
		let settled = false
		const finish = () => {
			if (settled) return
			settled = true
			window.clearTimeout(timer)
			peer.removeEventListener('icegatheringstatechange', changed)
			resolve()
		}
		const changed = () => {
			if (peer.iceGatheringState === 'complete') finish()
		}
		const timer = window.setTimeout(finish, timeout)
		peer.addEventListener('icegatheringstatechange', changed)
	})
}

function preferOpus(transceiver) {
	if (!transceiver?.setCodecPreferences || !globalThis.RTCRtpSender?.getCapabilities) return
	const codecs = globalThis.RTCRtpSender.getCapabilities('audio')?.codecs || []
	const opus = codecs.filter((codec) => codec.mimeType?.toLowerCase() === 'audio/opus')
	if (opus.length) transceiver.setCodecPreferences(opus)
}

export class WhatsAppWebRTCSession {
	constructor(configuration = {}, handlers = {}) {
		this.configuration = configuration || {}
		this.handlers = handlers
		this.peer = null
		this.localStream = null
		this.remoteStream = null
		this.muted = false
	}

	static supported() {
		return Boolean(
			globalThis.RTCPeerConnection && globalThis.navigator?.mediaDevices?.getUserMedia,
		)
	}

	async prepareOutgoing() {
		await this.#prepareMedia()
		const offer = await this.peer.createOffer({ offerToReceiveAudio: true })
		await this.peer.setLocalDescription(offer)
		await waitForIceGathering(this.peer)
		return this.#localDescription('offer')
	}

	async prepareIncoming(remoteSession) {
		const remote = parseCallSession(remoteSession)
		if (remote?.type !== 'offer') throw new Error('The incoming call offer is unavailable.')
		await this.#prepareMedia()
		await this.peer.setRemoteDescription(remote)
		const answer = await this.peer.createAnswer()
		await this.peer.setLocalDescription(answer)
		await waitForIceGathering(this.peer)
		return this.#localDescription('answer')
	}

	async applyRemoteAnswer(remoteSession) {
		const remote = parseCallSession(remoteSession)
		if (!this.peer || remote?.type !== 'answer') return false
		if (this.peer.currentRemoteDescription?.sdp === remote.sdp) return true
		await this.peer.setRemoteDescription(remote)
		return true
	}

	async waitUntilConnected(timeout = 5000) {
		if (['connected', 'completed'].includes(this.peer?.connectionState)) return true
		return new Promise((resolve) => {
			let settled = false
			const finish = (connected) => {
				if (settled) return
				settled = true
				window.clearTimeout(timer)
				this.peer?.removeEventListener('connectionstatechange', changed)
				resolve(connected)
			}
			const changed = () => {
				if (this.peer?.connectionState === 'connected') finish(true)
				if (['failed', 'closed'].includes(this.peer?.connectionState)) finish(false)
			}
			const timer = window.setTimeout(() => finish(false), timeout)
			this.peer?.addEventListener('connectionstatechange', changed)
		})
	}

	setMuted(muted) {
		this.muted = Boolean(muted)
		for (const track of this.localStream?.getAudioTracks?.() || []) track.enabled = !this.muted
		return this.muted
	}

	close() {
		for (const track of this.localStream?.getTracks?.() || []) track.stop()
		for (const track of this.remoteStream?.getTracks?.() || []) track.stop()
		this.peer?.close()
		this.peer = null
		this.localStream = null
		this.remoteStream = null
	}

	async #prepareMedia() {
		if (!WhatsAppWebRTCSession.supported()) {
			throw new Error('Calling requires a supported browser and microphone access.')
		}
		if (this.peer) return
		this.localStream = await navigator.mediaDevices.getUserMedia(AUDIO_CONSTRAINTS)
		this.peer = new RTCPeerConnection(this.configuration)
		this.peer.addEventListener('connectionstatechange', () => {
			this.handlers.onConnectionState?.(this.peer?.connectionState || 'closed')
		})
		this.peer.addEventListener('iceconnectionstatechange', () => {
			this.handlers.onIceState?.(this.peer?.iceConnectionState || 'closed')
		})
		this.peer.addEventListener('track', (event) => {
			this.remoteStream = event.streams?.[0] || this.remoteStream
			if (!this.remoteStream && globalThis.MediaStream) {
				this.remoteStream = new MediaStream([event.track])
			}
			this.handlers.onRemoteStream?.(this.remoteStream)
		})
		const track = this.localStream.getAudioTracks()[0]
		if (!track) throw new Error('No microphone audio track is available.')
		const transceiver = this.peer.addTransceiver(track, {
			direction: 'sendrecv',
			streams: [this.localStream],
		})
		preferOpus(transceiver)
	}

	#localDescription(expectedType) {
		const description = this.peer?.localDescription
		if (!description?.sdp || description.type !== expectedType) {
			throw new Error('The secure audio connection could not be prepared.')
		}
		return { sdp_type: expectedType, sdp: description.sdp }
	}
}
