import assert from 'node:assert/strict'
import test from 'node:test'

import { filterAndRankConversations } from './conversationSearch.js'

const rows = [
	{
		name: 'one',
		display_name: 'Mohammed Anas',
		phone_number: '919876543210',
		contact_teams: [{ team_name: 'North Sales' }],
		latest_message: { body: 'Packing slip is ready' },
	},
	{
		name: 'two',
		display_name: 'Sakthi Kumar',
		phone_number: '919111111111',
		latest_message: { body: 'Good morning' },
	},
]

test('finds contacts despite a small spelling error', () => {
	assert.deepEqual(
		filterAndRankConversations(rows, 'Mohamad').map((row) => row.name),
		['one'],
	)
})

test('searches partial phone numbers, teams, and message previews', () => {
	assert.equal(filterAndRankConversations(rows, '654321')[0].name, 'one')
	assert.equal(filterAndRankConversations(rows, 'north')[0].name, 'one')
	assert.equal(filterAndRankConversations(rows, 'packing ready')[0].name, 'one')
})

test('ranks exact contact matches ahead of loose matches', () => {
	assert.equal(filterAndRankConversations(rows, 'Sakthi')[0].name, 'two')
})
