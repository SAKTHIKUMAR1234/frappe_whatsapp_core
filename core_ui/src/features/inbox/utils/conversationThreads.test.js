import assert from 'node:assert/strict'
import test from 'node:test'

import { presentConversationThreads, threadStatusTone } from './conversationThreads.js'

test('presents customer threads by latest covered activity without exposing record ids', () => {
	const rows = presentConversationThreads([
		{
			name: 'random-record-name',
			title: 'Delivery follow-up',
			message_count: 4,
			first_message: 'first',
			last_message: 'last',
			first_message_at: '2026-08-20T10:00:00Z',
			last_message_at: '2026-08-20T10:30:00Z',
		},
		{
			name: 'another-record-name',
			title: 'Payment query',
			messages: ['payment-first'],
			first_message_at: '2026-08-21T10:00:00Z',
		},
	])

	assert.equal(rows[0].title, 'Payment query')
	assert.equal(rows[0].firstMessage, 'payment-first')
	assert.equal(rows[1].messageCount, 4)
	assert.equal(rows[1].lastMessage, 'last')
	assert.equal(Object.hasOwn(rows[0], 'recordLabel'), false)
})

test('maps thread states to restrained product tones', () => {
	assert.equal(threadStatusTone('Open'), 'info')
	assert.equal(threadStatusTone('Waiting'), 'warn')
	assert.equal(threadStatusTone('Resolved'), 'success')
	assert.equal(threadStatusTone('Archived'), 'secondary')
})
