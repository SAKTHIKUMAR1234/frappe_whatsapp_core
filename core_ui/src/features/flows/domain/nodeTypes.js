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
			accepted_media_types: ['image', 'document', 'audio', 'video'],
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
	return {
		nodes: graph.nodes.map((node) => ({
			id: node.id,
			type: 'core',
			position: node.position || { x: 0, y: 0 },
			data: {
				type: node.type,
				config: hydrateValue(node.config || {}),
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
