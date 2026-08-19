export const NODE_TYPES = [
	{ type: 'send_template', label: 'Template', icon: 'send' },
	{ type: 'send_flow', label: 'Meta Flow', icon: 'flow' },
	{ type: 'send_message', label: 'Message', icon: 'message' },
	{ type: 'ask_input', label: 'Collect input', icon: 'input' },
	{ type: 'condition', label: 'Branch', icon: 'branch' },
	{ type: 'action', label: 'Action / connector', icon: 'action' },
	{ type: 'wait', label: 'Wait', icon: 'wait' },
	{ type: 'human_handoff', label: 'Human handoff', icon: 'handoff' },
	{ type: 'end', label: 'End', icon: 'end' },
]

export function createNodeConfig(type) {
	const label = NODE_TYPES.find((item) => item.type === type)?.label || type

	const configurations = {
		send_template: { label, template: '', language: 'en' },
		send_flow: {
			label,
			flow_id: '',
			message: 'Please complete this form.',
			flow_cta: 'Open',
			flow_action: 'navigate',
			screen: '',
			response_key: 'form_response',
			data: {},
		},
		send_message: { label, message: '' },
		ask_text: {
			label,
			message: '',
			answer_key: '',
			required: true,
		},
		ask_choice: {
			label,
			message: '',
			answer_key: '',
			button_label: 'Choose',
			options: [
				{ label: 'Yes', value: 'yes' },
				{ label: 'No', value: 'no' },
			],
		},
		ask_input: {
			label,
			message: '',
			answer_key: '',
			input_type: 'text',
			required: true,
			button_label: 'Choose',
			options: [
				{ label: 'Option 1', value: 'option_1' },
				{ label: 'Option 2', value: 'option_2' },
			],
			options_from: '',
			minimum: '',
			maximum: '',
			integer_only: false,
			accepted_media_types: ['image', 'document', 'audio', 'video', 'sticker'],
			validation_message: '',
		},
		action: {
			label,
			action: 'context.set',
			input: {},
			output_key: 'action_result',
		},
		wait: {
			label,
			resume_on: 'event',
		},
		human_handoff: {
			label,
			reason: '',
			message: '',
		},
		end: { label, message: '' },
	}

	return configurations[type] || { label }
}

export function serializeFlowGraph({ nodes, edges, triggers }) {
	return {
		schema_version: 1,
		triggers,
		nodes: nodes.map((node) => ({
			id: node.id,
			type: node.data.type,
			position: node.position,
			config: serializeValue(node.data.config || {}),
		})),
		edges: edges.map((edge) => ({
			id: edge.id,
			source: edge.source,
			target: edge.target,
			...(edge.data?.default ? { default: true } : {}),
			...(edge.data?.when?.left?.var ? { when: edge.data.when } : {}),
			...(edge.data?.max_traversals
				? { max_traversals: Number(edge.data.max_traversals) }
				: {}),
		})),
	}
}

export function hydrateFlowGraph(graph) {
	const positions = flowPositions(graph.nodes || [], graph.edges || [])
	return {
		nodes: graph.nodes.map((node) => ({
			id: node.id,
			type: 'core',
			position: node.position || positions.get(node.id) || { x: 0, y: 0 },
			data: {
				type: node.type,
				config: {
					label: humanizeNodeId(node.id),
					...hydrateValue(node.config || {}),
				},
			},
		})),
		edges: graph.edges.map((edge) => ({
			id: edge.id,
			source: edge.source,
			target: edge.target,
			type: 'smoothstep',
			data: {
				when: edge.when,
				default: edge.default,
				max_traversals: edge.max_traversals,
			},
		})),
		triggers: graph.triggers || [],
	}
}

function flowPositions(nodes, edges) {
	if (!nodes.length || nodes.every((node) => validPosition(node.position))) {
		return new Map()
	}

	const order = new Map(nodes.map((node, index) => [node.id, index]))
	const nodeIds = new Set(order.keys())
	const outgoing = new Map(nodes.map((node) => [node.id, []]))
	for (const edge of edges) {
		if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue
		outgoing.get(edge.source).push(edge)
	}

	// Imported fixture graphs intentionally omit canvas coordinates. Remove only
	// traversal back-edges while calculating layers so bounded loops remain visible
	// without collapsing every node on top of (0, 0).
	const state = new Map()
	const backEdges = new Set()
	function visit(nodeId) {
		state.set(nodeId, 1)
		for (const edge of outgoing.get(nodeId) || []) {
			if (state.get(edge.target) === 1) {
				backEdges.add(edge.id)
				continue
			}
			if (!state.has(edge.target)) visit(edge.target)
		}
		state.set(nodeId, 2)
	}
	for (const node of nodes) {
		if (!state.has(node.id)) visit(node.id)
	}

	const levels = new Map(nodes.map((node) => [node.id, 0]))
	const indegree = new Map(nodes.map((node) => [node.id, 0]))
	for (const edge of edges) {
		if (
			backEdges.has(edge.id) ||
			!nodeIds.has(edge.source) ||
			!nodeIds.has(edge.target)
		) {
			continue
		}
		indegree.set(edge.target, indegree.get(edge.target) + 1)
	}
	const queue = nodes
		.filter((node) => indegree.get(node.id) === 0)
		.map((node) => node.id)
	while (queue.length) {
		const source = queue.shift()
		for (const edge of outgoing.get(source) || []) {
			if (backEdges.has(edge.id)) continue
			levels.set(edge.target, Math.max(levels.get(edge.target), levels.get(source) + 1))
			indegree.set(edge.target, indegree.get(edge.target) - 1)
			if (indegree.get(edge.target) === 0) queue.push(edge.target)
		}
	}

	const columns = new Map()
	for (const node of nodes) {
		const level = levels.get(node.id) || 0
		if (!columns.has(level)) columns.set(level, [])
		columns.get(level).push(node.id)
	}
	const widestColumn = Math.max(...[...columns.values()].map((column) => column.length))
	const positions = new Map()
	for (const [level, column] of [...columns.entries()].sort(([left], [right]) => left - right)) {
		column.sort((left, right) => order.get(left) - order.get(right))
		const topOffset = ((widestColumn - column.length) * 150) / 2
		column.forEach((nodeId, row) => {
			positions.set(nodeId, {
				x: 60 + level * 250,
				y: 80 + topOffset + row * 150,
			})
		})
	}
	return positions
}

function validPosition(position) {
	return Number.isFinite(position?.x) && Number.isFinite(position?.y)
}

function humanizeNodeId(value) {
	const label = String(value || '')
		.replaceAll(/[-_]+/g, ' ')
		.replaceAll(/\s+/g, ' ')
		.trim()
	return label ? label.charAt(0).toUpperCase() + label.slice(1) : 'Flow step'
}

function serializeValue(value) {
	if (typeof value === 'string') {
		const match = value.trim().match(/^\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}$/)
		if (match) return { var: match[1] }
		return value
	}
	if (Array.isArray(value)) return value.map(serializeValue)
	if (value && typeof value === 'object') {
		return Object.fromEntries(
			Object.entries(value).map(([key, item]) => [key, serializeValue(item)]),
		)
	}
	return value
}

function hydrateValue(value) {
	if (Array.isArray(value)) return value.map(hydrateValue)
	if (value && typeof value === 'object') {
		if (Object.keys(value).length === 1 && typeof value.var === 'string') {
			return `{{${value.var}}}`
		}
		return Object.fromEntries(
			Object.entries(value).map(([key, item]) => [key, hydrateValue(item)]),
		)
	}
	return value
}
