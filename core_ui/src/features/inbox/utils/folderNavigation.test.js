import assert from 'node:assert/strict'
import test from 'node:test'

import { foldersMatch } from './folderNavigation.js'

test('custom folders match by unique name rather than shared type', () => {
	const priority = { name: 'priority', folder_type: 'Custom' }
	const followUp = { name: 'follow-up', folder_type: 'Custom' }

	assert.equal(foldersMatch(priority, { ...priority }), true)
	assert.equal(foldersMatch(priority, followUp), false)
})

test('the built-in Important alias remains canonical before its row exists', () => {
	assert.equal(
		foldersMatch(
			{ name: 'important', folder_type: 'Important' },
			{ name: 'generated-important-row', folder_type: 'Important' },
		),
		true,
	)
})
