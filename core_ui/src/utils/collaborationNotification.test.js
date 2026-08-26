import assert from 'node:assert/strict'
import test from 'node:test'

import { collaborationNotificationRoute } from './collaborationNotification.js'

test('message-linked notifications target the referenced message and retain note context', () => {
	assert.deepEqual(
		collaborationNotificationRoute(
			{
				conversation: 'conversation-1',
				document_name: 'comment-1',
				comment: { message_references: ['', 'message-2', 'message-3'] },
			},
			'notification-1:1',
		),
		{
			name: 'inbox',
			params: { conversation: 'conversation-1' },
			query: {
				comment: 'comment-1',
				message: 'message-2',
				focus: 'notification-1:1',
			},
		},
	)
})

test('notifications without message references fall back to the internal note', () => {
	assert.deepEqual(
		collaborationNotificationRoute({
			conversation: 'conversation-1',
			document_name: 'comment-1',
			comment: { message_references: [] },
		}),
		{
			name: 'inbox',
			params: { conversation: 'conversation-1' },
			query: { comment: 'comment-1' },
		},
	)
})

test('malformed notification data produces a safe inbox route', () => {
	assert.deepEqual(collaborationNotificationRoute(null), {
		name: 'inbox',
		params: {},
		query: {},
	})
})
