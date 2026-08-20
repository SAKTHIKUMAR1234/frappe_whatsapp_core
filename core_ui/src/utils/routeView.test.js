import assert from 'node:assert/strict'
import test from 'node:test'

import { routeComponentKey } from './routeView.js'

test('conversation navigation keeps one mounted inbox workspace', () => {
	assert.equal(
		routeComponentKey({ name: 'inbox', fullPath: '/inbox/conversation-a' }),
		routeComponentKey({ name: 'inbox', fullPath: '/inbox/conversation-b' }),
	)
})

test('record builders remount when their full route changes', () => {
	assert.notEqual(
		routeComponentKey({ name: 'flow-builder', fullPath: '/flows/a' }),
		routeComponentKey({ name: 'flow-builder', fullPath: '/flows/b' }),
	)
})
