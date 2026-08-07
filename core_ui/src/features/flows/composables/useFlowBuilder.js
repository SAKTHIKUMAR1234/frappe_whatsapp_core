import { computed, nextTick, ref } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import {
	createNodeConfig,
	hydrateFlowGraph,
	serializeFlowGraph,
} from '@/features/flows/domain/nodeTypes'
import { getFlow, publishFlow, saveFlowDraft } from '@/features/flows/services/flowService'
import { errorMessage } from '@/services/frappe'

export function useFlowBuilder({ flowName, toast }) {
	const nodes = ref([])
	const edges = ref([])
	const triggers = ref([])
	const catalog = ref({
		actions: [],
		templates: [],
	})
	const flow = ref({
		title: flowName,
		status: 'Draft',
	})
	const selected = ref(null)
	const saving = ref(false)
	const validating = ref(false)
	const publishing = ref(false)
	let itemCounter = 20

	const {
		addEdges,
		addNodes,
		fitView,
		onConnect,
		onEdgeClick,
		onNodeClick,
		project,
		removeEdges,
		removeNodes,
	} = useVueFlow()

	const selectedNode = computed(() => {
		if (selected.value?.kind !== 'node') return null
		return nodes.value.find((node) => node.id === selected.value.id)
	})

	const selectedEdge = computed(() => {
		if (selected.value?.kind !== 'edge') return null
		return edges.value.find((edge) => edge.id === selected.value.id)
	})

	const choiceOptionsText = computed({
		get() {
			const options = selectedNode.value?.data.config.options || []
			return options
				.map((option) => {
					if (typeof option === 'string') return option
					return `${option.label}|${option.value}`
				})
				.join('\n')
		},
		set(value) {
			if (!selectedNode.value) return
			selectedNode.value.data.config.options = value
				.split('\n')
				.filter(Boolean)
				.map((line) => {
					const [label, rawValue] = line.split('|')
					return {
						label: label.trim(),
						value: (rawValue || label).trim(),
					}
				})
		},
	})

	onConnect((connection) => {
		addEdges([
			{
				id: `edge-${++itemCounter}`,
				...connection,
				type: 'smoothstep',
				data: {},
			},
		])
	})

	onNodeClick(({ node }) => {
		selected.value = {
			kind: 'node',
			id: node.id,
		}
	})

	onEdgeClick(({ edge }) => {
		selected.value = {
			kind: 'edge',
			id: edge.id,
		}
	})

	function addNodeFromDrop(event) {
		const type = event.dataTransfer.getData('application/core-flow')
		if (!type) return

		const canvasBounds = event.currentTarget.getBoundingClientRect()
		const id = `${type}-${++itemCounter}`

		addNodes([
			{
				id,
				type: 'core',
				position: project({
					x: event.clientX - canvasBounds.left,
					y: event.clientY - canvasBounds.top,
				}),
				data: {
					type,
					config: createNodeConfig(type),
				},
			},
		])

		selected.value = {
			kind: 'node',
			id,
		}
	}

	function deleteSelected() {
		if (selected.value?.kind === 'node') {
			removeNodes([selected.value.id])
		}
		if (selected.value?.kind === 'edge') {
			removeEdges([selected.value.id])
		}
		selected.value = null
	}

	function ensureEdgeCondition() {
		if (!selectedEdge.value) return
		selectedEdge.value.data ||= {}
		selectedEdge.value.data.when ||= {
			op: 'eq',
			left: { var: 'answers.value' },
			right: 'yes',
		}
	}

	function graph() {
		return serializeFlowGraph({
			nodes: nodes.value,
			edges: edges.value,
			triggers: triggers.value,
		})
	}

	async function load() {
		const result = await getFlow(flowName)
		const hydrated = hydrateFlowGraph(result.graph)

		flow.value = result
		catalog.value = result.catalog || catalog.value
		nodes.value = hydrated.nodes
		edges.value = hydrated.edges
		triggers.value = hydrated.triggers

		await nextTick()
		window.setTimeout(() => {
			fitView({
				padding: 0.2,
				maxZoom: 1,
			})
		}, 500)
	}

	async function save({ notify = true } = {}) {
		saving.value = true
		try {
			const result = await saveFlowDraft(flowName, graph())
			if (notify) {
				toast.add({
					severity: 'success',
					summary: 'Draft saved',
					detail: result.errors.length
						? `${result.errors.length} validation issues remain`
						: 'Ready to publish',
					life: 2600,
				})
			}
			return result
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Draft not saved',
				detail: errorMessage(error),
				life: 5000,
			})
			return null
		} finally {
			saving.value = false
		}
	}

	async function validate() {
		validating.value = true
		try {
			const result = await save({ notify: false })
			if (!result) return
			if (result.errors.length) {
				toast.add({
					severity: 'warn',
					summary: 'Flow needs attention',
					detail: result.errors[0],
					life: 5000,
				})
				return
			}
			toast.add({
				severity: 'success',
				summary: 'Flow is valid',
				detail: 'Every node and branch passed validation.',
				life: 3000,
			})
		} finally {
			validating.value = false
		}
	}

	async function publish() {
		publishing.value = true
		try {
			const validation = await save({ notify: false })
			if (!validation) return
			if (validation.errors.length) {
				toast.add({
					severity: 'error',
					summary: 'Cannot publish',
					detail: validation.errors[0],
					life: 5000,
				})
				return
			}

			const result = await publishFlow(flowName)
			flow.value.status = 'Published'
			toast.add({
				severity: 'success',
				summary: `Version ${result.version} published`,
				detail: 'Running conversations are pinned safely.',
				life: 3500,
			})
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Flow not published',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			publishing.value = false
		}
	}

	return {
		nodes,
		edges,
		triggers,
		catalog,
		flow,
		selected,
		selectedNode,
		selectedEdge,
		choiceOptionsText,
		saving,
		validating,
		publishing,
		addNodeFromDrop,
		deleteSelected,
		ensureEdgeCondition,
		load,
		save,
		validate,
		publish,
	}
}
