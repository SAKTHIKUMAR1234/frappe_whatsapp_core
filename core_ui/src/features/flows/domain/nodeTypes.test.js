import assert from 'node:assert/strict'
import test from 'node:test'

import { hydrateFlowGraph } from './nodeTypes.js'

test('imported flow nodes receive readable labels and non-overlapping positions', () => {
	const graph = {
		nodes: [
			{ id: 'start', type: 'start', config: {} },
			{ id: 'collect_title', type: 'ask_input', config: {} },
			{ id: 'choice', type: 'condition', config: {} },
			{ id: 'create_ticket', type: 'action', config: {} },
			{ id: 'end', type: 'end', config: {} },
		],
		edges: [
			{ id: 'e1', source: 'start', target: 'collect_title' },
			{ id: 'e2', source: 'collect_title', target: 'choice' },
			{ id: 'e3', source: 'choice', target: 'create_ticket' },
			{ id: 'e4', source: 'create_ticket', target: 'choice' },
			{ id: 'e5', source: 'create_ticket', target: 'end' },
		],
		triggers: [],
	}

	const hydrated = hydrateFlowGraph(graph)
	const coordinates = hydrated.nodes.map(({ position }) => `${position.x}:${position.y}`)

	assert.equal(new Set(coordinates).size, graph.nodes.length)
	assert.equal(hydrated.nodes[1].data.config.label, 'Collect title')
	assert.equal(hydrated.nodes[3].data.config.label, 'Create ticket')
})

test('saved operator positions and labels remain unchanged', () => {
	const graph = {
		nodes: [
			{
				id: 'custom',
				type: 'action',
				position: { x: 321, y: 123 },
				config: { label: 'My action' },
			},
		],
		edges: [],
		triggers: [],
	}

	const hydrated = hydrateFlowGraph(graph)

	assert.deepEqual(hydrated.nodes[0].position, { x: 321, y: 123 })
	assert.equal(hydrated.nodes[0].data.config.label, 'My action')
})
