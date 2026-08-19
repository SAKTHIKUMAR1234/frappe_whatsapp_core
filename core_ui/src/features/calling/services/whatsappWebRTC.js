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
		!String(call?.handled_by || '').trim() &&
		String(call?.direction || '').toLowerCase() === 'inbound' &&
		['connect', 'ringing', 'received'].includes(normalizedCallStatus(call?.status)) &&
		session?.type === 'offer'
	)
}

export function nextIncomingCall(calls, activeCallId = '') {
	return (Array.isArray(calls) ? calls : []).find(
		(call) => isIncomingRinging(call) && call.call_id !== activeCallId,
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
		this.recording = null
	}

	static supported() {
		return Boolean(
			globalThis.RTCPeerConnection && globalThis.navigator?.mediaDevices?.getUserMedia,
		)
	}

	async prepareOutgoing() {
		await this.#prepareMedia()
		this.#attachOutgoingTrack()
		const offer = await this.peer.createOffer({ offerToReceiveAudio: true })
		await this.peer.setLocalDescription(offer)
		await waitForIceGathering(this.peer)
		return this.#localDescription('offer')
	}

	async prepareIncoming(remoteSession) {
		const remote = parseCallSession(remoteSession)
		if (remote?.type !== 'offer') throw new Error('The incoming call offer is unavailable.')
		await this.#prepareMedia()
		// Apply Meta's offer before attaching the microphone. Explicit transceivers
		// created before a remote offer are not associated with that offer's media
		// section, which leaves the answer receive-only and causes one-way audio.
		await this.peer.setRemoteDescription(remote)
		await this.#attachIncomingTrack()
		const answer = await this.peer.createAnswer()
		await this.peer.setLocalDescription(answer)
		await waitForIceGathering(this.peer)
		this.#assertSendingAudio()
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
		const connected = () =>
			this.peer?.connectionState === 'connected' ||
			['connected', 'completed'].includes(this.peer?.iceConnectionState)
		if (connected()) return true
		return new Promise((resolve) => {
			let settled = false
			const finish = (connected) => {
				if (settled) return
				settled = true
				globalThis.clearTimeout(timer)
				this.peer?.removeEventListener('connectionstatechange', changed)
				this.peer?.removeEventListener('iceconnectionstatechange', changed)
				resolve(connected)
			}
			const changed = () => {
				if (connected()) finish(true)
				if (
					['failed', 'closed'].includes(this.peer?.connectionState) ||
					['failed', 'closed'].includes(this.peer?.iceConnectionState)
				)
					finish(false)
			}
			const timer = globalThis.setTimeout(() => finish(false), timeout)
			this.peer?.addEventListener('connectionstatechange', changed)
			this.peer?.addEventListener('iceconnectionstatechange', changed)
		})
	}

	setMuted(muted) {
		this.muted = Boolean(muted)
		for (const track of this.localStream?.getAudioTracks?.() || []) track.enabled = !this.muted
		return this.muted
	}

	async startMixedRecording() {
		if (this.recording?.recorder?.state === 'recording') return true
		const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext
		if (!globalThis.MediaRecorder || !AudioContext) return false
		if (!this.localStream?.getAudioTracks?.().length) return false
		if (!this.remoteStream?.getAudioTracks?.().length) return false

		const context = new AudioContext()
		if (context.state === 'suspended') await context.resume()
		const destination = context.createMediaStreamDestination()
		const localSource = context.createMediaStreamSource(this.localStream)
		const remoteSource = context.createMediaStreamSource(this.remoteStream)
		localSource.connect(destination)
		remoteSource.connect(destination)
		const mimeType =
			['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm'].find((candidate) =>
				globalThis.MediaRecorder.isTypeSupported?.(candidate),
			) || ''
		const recorder = new globalThis.MediaRecorder(
			destination.stream,
			mimeType ? { mimeType } : undefined,
		)
		const chunks = []
		recorder.addEventListener('dataavailable', (event) => {
			if (event.data?.size) chunks.push(event.data)
		})
		this.recording = {
			context,
			destination,
			localSource,
			remoteSource,
			recorder,
			chunks,
			mimeType: recorder.mimeType || mimeType || 'audio/webm',
		}
		recorder.start(1000)
		return true
	}

	stopMixedRecording() {
		const recording = this.recording
		this.recording = null
		if (!recording?.recorder || recording.recorder.state === 'inactive') {
			this.#closeRecordingGraph(recording)
			return Promise.resolve(null)
		}
		return new Promise((resolve, reject) => {
			let finished = false
			const finish = () => {
				if (finished) return
				finished = true
				const blob = recording.chunks.length
					? new Blob(recording.chunks, { type: recording.mimeType })
					: null
				this.#closeRecordingGraph(recording)
				resolve(blob?.size ? blob : null)
			}
			const fail = (event) => {
				if (finished) return
				finished = true
				this.#closeRecordingGraph(recording)
				reject(event?.error || new Error('The mixed call recording failed.'))
			}
			recording.recorder.addEventListener('stop', finish, { once: true })
			recording.recorder.addEventListener('error', fail, { once: true })
			try {
				recording.recorder.stop()
			} catch (error) {
				fail({ error })
			}
		})
	}

	close() {
		if (this.recording) {
			try {
				this.recording.recorder?.stop()
			} catch {
				// The recorder may already be stopping during call cleanup.
			}
			this.#closeRecordingGraph(this.recording)
			this.recording = null
		}
		for (const track of this.localStream?.getTracks?.() || []) track.stop()
		for (const track of this.remoteStream?.getTracks?.() || []) track.stop()
		this.peer?.close()
		this.peer = null
		this.localStream = null
		this.remoteStream = null
	}

	#closeRecordingGraph(recording) {
		try {
			recording?.localSource?.disconnect()
			recording?.remoteSource?.disconnect()
		} catch {
			// A browser may already have disconnected a source as media ended.
		}
		for (const track of recording?.destination?.stream?.getTracks?.() || []) track.stop()
		recording?.context?.close?.()?.catch?.(() => {})
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
		this.#microphoneTrack()
	}

	#microphoneTrack() {
		const track = this.localStream?.getAudioTracks?.()[0]
		if (!track || track.readyState === 'ended') {
			throw new Error('No microphone audio track is available.')
		}
		return track
	}

	#attachOutgoingTrack() {
		const track = this.#microphoneTrack()
		const transceiver = this.peer.addTransceiver(track, {
			direction: 'sendrecv',
			streams: [this.localStream],
		})
		preferOpus(transceiver)
	}

	async #attachIncomingTrack() {
		const transceiver = this.peer
			.getTransceivers()
			.find((item) => item.receiver?.track?.kind === 'audio')
		if (!transceiver?.sender) {
			throw new Error('The incoming call did not offer an audio connection.')
		}
		const track = this.#microphoneTrack()
		await transceiver.sender.replaceTrack(track)
		transceiver.sender.setStreams?.(this.localStream)
		transceiver.direction = 'sendrecv'
		preferOpus(transceiver)
	}

	#assertSendingAudio() {
		const transceiver = this.peer
			.getTransceivers()
			.find((item) => item.receiver?.track?.kind === 'audio')
		const track = transceiver?.sender?.track
		if (
			!track ||
			track.readyState === 'ended' ||
			!['sendrecv', 'sendonly'].includes(transceiver.direction)
		) {
			throw new Error('The microphone could not be attached to the secure audio connection.')
		}
	}

	#localDescription(expectedType) {
		const description = this.peer?.localDescription
		if (!description?.sdp || description.type !== expectedType) {
			throw new Error('The secure audio connection could not be prepared.')
		}
		return { sdp_type: expectedType, sdp: description.sdp }
	}
}
