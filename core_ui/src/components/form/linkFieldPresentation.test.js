import test from 'node:test'
import assert from 'node:assert/strict'

import { findLinkOption, linkOptionLabel } from './linkFieldPresentation.js'

test('keeps the document name as the Link value while presenting its title field', () => {
	const team = { name: 'm3x8k2p4', team_name: 'North Sales' }

	assert.equal(findLinkOption([team], 'm3x8k2p4', 'name'), team)
	assert.equal(linkOptionLabel(team, 'team_name', 'name'), 'North Sales')
})

test('does not bind a fuzzy search result to a different stored Link value', () => {
	const rows = [
		{ name: 'team-one', team_name: 'North Sales' },
		{ name: 'team-two', team_name: 'North Service' },
	]

	assert.equal(findLinkOption(rows, 'missing-team', 'name'), null)
})

test('falls back to the stored value when a record has no distinct title field', () => {
	const option = { name: 'support@example.com' }

	assert.equal(linkOptionLabel(option, 'full_name', 'name'), 'support@example.com')
})
