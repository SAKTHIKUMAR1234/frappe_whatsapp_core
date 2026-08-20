import assert from 'node:assert/strict'
import test from 'node:test'

import { describeFlowAsset } from './flowAsset.js'

test('summarizes a Meta Flow asset without exposing its JSON', () => {
	const summary = describeFlowAsset({
		version: '7.1',
		screens: [
			{
				id: 'WELCOME',
				title: 'Welcome',
				layout: {
					type: 'SingleColumnLayout',
					children: [{ type: 'TextHeading' }, { type: 'TextBody' }],
				},
			},
			{
				id: 'DONE',
				terminal: true,
				layout: { children: [{ type: 'Footer' }] },
			},
		],
	})

	assert.equal(summary.version, '7.1')
	assert.equal(summary.screenCount, 2)
	assert.equal(summary.componentCount, 3)
	assert.deepEqual(summary.screens[1], {
		id: 'DONE',
		title: 'DONE',
		terminal: true,
	})
})

test('returns an empty, render-safe summary for a missing asset', () => {
	assert.deepEqual(describeFlowAsset(null), {
		version: '—',
		screenCount: 0,
		componentCount: 0,
		screens: [],
	})
})
