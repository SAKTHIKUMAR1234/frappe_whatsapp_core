import assert from 'node:assert/strict'
import test from 'node:test'

import { acceptIncomingMedia } from './callSignaling.js'

test('pre-accepts, waits for media, then accepts without resending SDP', async () => {
	const requests = []
	const phases = []
	const result = await acceptIncomingMedia({
		invoke: async (request) => {
			requests.push(request)
			return { success: true }
		},
		rtc: { waitUntilConnected: async () => true },
		accountName: 'Hub Account',
		callId: 'CALL-1',
		answer: { sdp_type: 'answer', sdp: 'v=0' },
		onPhase: (phase) => phases.push(phase),
	})

	assert.equal(result.success, true)
	assert.deepEqual(phases, ['pre_accepting', 'connecting', 'accepting'])
	assert.deepEqual(
		requests.map((request) => request.action),
		['pre_accept', 'accept'],
	)
	assert.equal(requests[0].sdp, 'v=0')
	assert.equal('sdp' in requests[1], false)
})

test('does not accept a call whose media path never connects', async () => {
	const requests = []
	let claimed = false
	await assert.rejects(
		acceptIncomingMedia({
			invoke: async (request) => requests.push(request),
			rtc: { waitUntilConnected: async () => false },
			accountName: 'Hub Account',
			callId: 'CALL-2',
			answer: { sdp_type: 'answer', sdp: 'v=0' },
			onClaimed: () => {
				claimed = true
			},
		}),
		/UDP or TURN access/,
	)
	assert.deepEqual(
		requests.map((request) => request.action),
		['pre_accept'],
	)
	assert.equal(claimed, true)
})

test('does not claim a call when another operator won pre-accept', async () => {
	let claimed = false
	await assert.rejects(
		acceptIncomingMedia({
			invoke: async () => {
				throw new Error('This call is already being handled by another team member')
			},
			rtc: { waitUntilConnected: async () => true },
			accountName: 'Hub Account',
			callId: 'CALL-3',
			answer: { sdp_type: 'answer', sdp: 'v=0' },
			onClaimed: () => {
				claimed = true
			},
		}),
		/already being handled/,
	)
	assert.equal(claimed, false)
})
