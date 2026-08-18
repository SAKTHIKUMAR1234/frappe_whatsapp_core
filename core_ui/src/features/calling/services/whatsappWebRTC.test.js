import assert from 'node:assert/strict'
import test from 'node:test'

import {
	TERMINAL_CALL_STATES,
	isIncomingRinging,
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
})
