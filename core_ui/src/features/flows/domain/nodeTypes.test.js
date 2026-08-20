import assert from 'node:assert/strict'
import test from 'node:test'

import { arrangeFlowNodes, hydrateFlowGraph } from './nodeTypes.js'

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

test('published flow nodes with identical saved coordinates are laid out again', () => {
	const graph = {
		nodes: [
			{ id: 'start', type: 'start', position: { x: 0, y: 0 }, config: {} },
			{
				id: 'collect_description',
				type: 'ask_input',
				position: { x: 0, y: 0 },
				config: {},
			},
			{
				id: 'create_ticket',
				type: 'action',
				position: { x: 0, y: 0 },
				config: {},
			},
			{ id: 'end', type: 'end', position: { x: 0, y: 0 }, config: {} },
		],
		edges: [
			{ id: 'e1', source: 'start', target: 'collect_description' },
			{ id: 'e2', source: 'collect_description', target: 'create_ticket' },
			{ id: 'e3', source: 'create_ticket', target: 'end' },
		],
		triggers: [],
	}

	const hydrated = hydrateFlowGraph(graph)
	const coordinates = hydrated.nodes.map(({ position }) => `${position.x}:${position.y}`)

	assert.equal(new Set(coordinates).size, graph.nodes.length)
	assert.deepEqual(
		hydrated.nodes.map(({ position }) => position.x),
		[60, 310, 560, 810],
	)
})

test('explicit arrange replaces a valid but unhelpful operator layout', () => {
	const nodes = [
		{ id: 'start', position: { x: 40, y: 40 } },
		{ id: 'collect', position: { x: 60, y: 60 } },
		{ id: 'finish', position: { x: 80, y: 80 } },
	]
	const edges = [
		{ id: 'e1', source: 'start', target: 'collect' },
		{ id: 'e2', source: 'collect', target: 'finish' },
	]

	const arranged = arrangeFlowNodes(nodes, edges)

	assert.deepEqual(
		arranged.map(({ position }) => position.x),
		[60, 310, 560],
	)
	assert.equal(new Set(arranged.map(({ position }) => `${position.x}:${position.y}`)).size, 3)
})
