export const NODE_TYPES = [
	{ type: 'send_template', label: 'Template', icon: 'send' },
	{ type: 'send_message', label: 'Message', icon: 'message' },
	{ type: 'ask_text', label: 'Ask text', icon: 'text' },
	{ type: 'ask_choice', label: 'Ask choice', icon: 'choice' },
	{ type: 'condition', label: 'Branch', icon: 'branch' },
	{ type: 'action', label: 'Action / connector', icon: 'action' },
	{ type: 'wait', label: 'Wait', icon: 'wait' },
	{ type: 'human_handoff', label: 'Human handoff', icon: 'handoff' },
	{ type: 'end', label: 'End', icon: 'end' },
]

export function createNodeConfig(type) {
	const label = NODE_TYPES.find((item) => item.type === type)?.label || type

	const configurations = {
		send_template: { label, template: '' },
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
			options: [
				{ label: 'Yes', value: 'yes' },
				{ label: 'No', value: 'no' },
			],
		},
		action: {
			label,
			action: 'context.set',
			input: {},
		},
		wait: {
			label,
			resume_on: 'event',
		},
		human_handoff: {
			label,
			reason: '',
		},
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
			config: node.data.config || {},
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
	return {
		nodes: graph.nodes.map((node) => ({
			id: node.id,
			type: 'core',
			position: node.position || { x: 0, y: 0 },
			data: {
				type: node.type,
				config: node.config || {},
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
