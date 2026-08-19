import assert from 'node:assert/strict'
import test from 'node:test'

import {
	TERMINAL_CALL_STATES,
	WhatsAppWebRTCSession,
	isIncomingRinging,
	nextIncomingCall,
	normalizedCallStatus,
	parseCallSession,
} from './whatsappWebRTC.js'

test('normalizes provider call states', () => {
	assert.equal(normalizedCallStatus(' RINGING '), 'ringing')
	assert.equal(TERMINAL_CALL_STATES.has('terminated'), true)
})

test('accepts only valid SDP sessions', () => {
	assert.deepEqual(parseCallSession('{"sdp_type":"offer","sdp":"v=0"}'), {
		type: 'offer',
		sdp: 'v=0',
	})
	assert.equal(parseCallSession({ sdp_type: 'candidate', sdp: 'v=0' }), null)
	assert.equal(parseCallSession('not-json'), null)
})

test('identifies an actionable inbound offer', () => {
	assert.equal(
		isIncomingRinging({
			direction: 'Inbound',
			status: 'connect',
			session: { sdp_type: 'offer', sdp: 'v=0' },
		}),
		true,
	)
	assert.equal(
		isIncomingRinging({
			direction: 'Outbound',
			status: 'connect',
			session: { sdp_type: 'offer', sdp: 'v=0' },
		}),
		false,
	)
	assert.equal(
		isIncomingRinging({
			direction: 'Inbound',
			status: 'connect',
			handled_by: 'operator@example.com',
			session: { sdp_type: 'offer', sdp: 'v=0' },
		}),
		false,
	)
})

test('exposes the next unclaimed call after a teammate answers another call', () => {
	const offer = { sdp_type: 'offer', sdp: 'v=0' }
	const calls = [
		{
			call_id: 'CALL-1',
			direction: 'Inbound',
			status: 'pre_accept',
			handled_by: 'first.operator@example.com',
			session: offer,
		},
		{
			call_id: 'CALL-2',
			direction: 'Inbound',
			status: 'connect',
			session: offer,
		},
	]

	assert.equal(nextIncomingCall(calls)?.call_id, 'CALL-2')
})

test('binds the microphone to the audio transceiver created by the incoming offer', async (t) => {
	const operations = []
	const microphone = { kind: 'audio', enabled: true, readyState: 'live', stop() {} }
	const localStream = {
		getAudioTracks: () => [microphone],
		getTracks: () => [microphone],
	}
	const sender = {
		track: null,
		async replaceTrack(track) {
			operations.push('replaceTrack')
			this.track = track
		},
		setStreams(stream) {
			operations.push('setStreams')
			assert.equal(stream, localStream)
		},
	}
	const offeredAudio = {
		direction: 'recvonly',
		receiver: { track: { kind: 'audio' } },
		sender,
		setCodecPreferences() {},
	}

	class IncomingPeer {
		constructor() {
			this.iceGatheringState = 'complete'
			this.localDescription = null
			this.transceivers = []
		}

		addEventListener() {}
		removeEventListener() {}
		getTransceivers() {
			return this.transceivers
		}
		addTransceiver() {
			operations.push('addTransceiver')
			throw new Error('incoming calls must not create a disassociated transceiver')
		}
		async setRemoteDescription() {
			operations.push('setRemoteDescription')
			this.transceivers = [offeredAudio]
		}
		async createAnswer() {
			operations.push('createAnswer')
			assert.equal(sender.track, microphone)
			assert.equal(offeredAudio.direction, 'sendrecv')
			return { type: 'answer', sdp: 'v=0\r\na=sendrecv\r\n' }
		}
		async setLocalDescription(description) {
			operations.push('setLocalDescription')
			this.localDescription = description
		}
	}

	const previousPeer = globalThis.RTCPeerConnection
	const previousNavigator = globalThis.navigator
	Object.defineProperty(globalThis, 'RTCPeerConnection', {
		configurable: true,
		value: IncomingPeer,
	})
	Object.defineProperty(globalThis, 'navigator', {
		configurable: true,
		value: { mediaDevices: { getUserMedia: async () => localStream } },
	})
	t.after(() => {
		Object.defineProperty(globalThis, 'RTCPeerConnection', {
			configurable: true,
			value: previousPeer,
		})
		Object.defineProperty(globalThis, 'navigator', {
			configurable: true,
			value: previousNavigator,
		})
	})

	const rtc = new WhatsAppWebRTCSession()
	const answer = await rtc.prepareIncoming({ sdp_type: 'offer', sdp: 'v=0' })
	assert.deepEqual(answer, { sdp_type: 'answer', sdp: 'v=0\r\na=sendrecv\r\n' })
	assert.deepEqual(operations, [
		'setRemoteDescription',
		'replaceTrack',
		'setStreams',
		'createAnswer',
		'setLocalDescription',
	])
})

test('records a private mixed artifact from local and remote call audio', async (t) => {
	const connected = []
	const stopped = []
	const localStream = {
		getAudioTracks: () => [{ kind: 'audio' }],
	}
	const remoteStream = {
		getAudioTracks: () => [{ kind: 'audio' }],
	}
	const destinationTrack = { stop: () => stopped.push('destination') }
	const destination = {
		stream: { getTracks: () => [destinationTrack] },
	}
	const context = {
		state: 'running',
		createMediaStreamDestination: () => destination,
		createMediaStreamSource(stream) {
			return {
				connect(target) {
					connected.push([stream, target])
				},
				disconnect() {},
			}
		},
		async close() {},
	}
	class AudioContextMock {
		constructor() {
			return context
		}
	}
	class MediaRecorderMock {
		static isTypeSupported(value) {
			return value === 'audio/webm;codecs=opus'
		}

		constructor(stream, options) {
			assert.equal(stream, destination.stream)
			assert.equal(options.mimeType, 'audio/webm;codecs=opus')
			this.mimeType = options.mimeType
			this.state = 'inactive'
			this.listeners = new Map()
		}

		addEventListener(name, handler) {
			this.listeners.set(name, handler)
		}

		start() {
			this.state = 'recording'
		}

		stop() {
			this.listeners.get('dataavailable')?.({
				data: new Blob(['both-speakers'], { type: this.mimeType }),
			})
			this.state = 'inactive'
			this.listeners.get('stop')?.()
		}
	}
	const previousAudioContext = globalThis.AudioContext
	const previousMediaRecorder = globalThis.MediaRecorder
	globalThis.AudioContext = AudioContextMock
	globalThis.MediaRecorder = MediaRecorderMock
	t.after(() => {
		globalThis.AudioContext = previousAudioContext
		globalThis.MediaRecorder = previousMediaRecorder
	})

	const rtc = new WhatsAppWebRTCSession()
	rtc.localStream = localStream
	rtc.remoteStream = remoteStream
	assert.equal(await rtc.startMixedRecording(), true)
	assert.deepEqual(connected, [
		[localStream, destination],
		[remoteStream, destination],
	])
	const artifact = await rtc.stopMixedRecording()
	assert.equal(artifact.type, 'audio/webm;codecs=opus')
	assert.equal(await artifact.text(), 'both-speakers')
	assert.deepEqual(stopped, ['destination'])
})
