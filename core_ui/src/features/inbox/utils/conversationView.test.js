import assert from 'node:assert/strict'
import test from 'node:test'

import { conversationViewStorageKey, defaultConversationView } from './conversationView.js'

test('summarized conversations open in compact mode by default', () => {
	assert.equal(
		defaultConversationView({ contact_summary: { summary: 'A useful summary' } }),
		'summary',
	)
	assert.equal(defaultConversationView({ topics: [{ name: 'topic-1' }] }), 'summary')
	assert.equal(defaultConversationView({ contact_summary: {}, topics: [] }), 'chat')
})

test('a per-conversation operator choice overrides the default', () => {
	assert.equal(defaultConversationView({ topics: [{}] }, 'chat'), 'chat')
	assert.equal(defaultConversationView({}, 'summary'), 'summary')
	assert.equal(
		conversationViewStorageKey('conversation-1'),
		'whatsapp:conversation-view:conversation-1',
	)
})
