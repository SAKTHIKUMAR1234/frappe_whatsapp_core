<script setup>
	import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import { Background } from '@vue-flow/background'
	import { Controls } from '@vue-flow/controls'
	import { VueFlow } from '@vue-flow/core'
	import Button from 'primevue/button'
	import Drawer from 'primevue/drawer'
	import { ListTree, PanelRight, Sparkles } from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'
	import FlowInspector from '@/features/flows/components/FlowInspector.vue'
	import FlowNode from '@/features/flows/components/FlowNode.vue'
	import FlowPalette from '@/features/flows/components/FlowPalette.vue'
	import FlowToolbar from '@/features/flows/components/FlowToolbar.vue'
	import FlowTriggerDrawer from '@/features/flows/components/FlowTriggerDrawer.vue'
	import { useFlowBuilder } from '@/features/flows/composables/useFlowBuilder'
	import { errorMessage } from '@/services/frappe'

	const route = useRoute()
	const router = useRouter()
	const toast = useToast()
	const loading = ref(true)
	const mobile = ref(false)
	const paletteVisible = ref(false)
	const inspectorVisible = ref(false)
	const triggerDrawerVisible = ref(false)
	const canvas = ref(null)
	const flowBuilder = useFlowBuilder({
		flowName: String(route.params.flowName || ''),
		toast,
	})

	function updateViewport() {
		mobile.value = window.innerWidth < 900
		if (!mobile.value) {
			paletteVisible.value = false
			inspectorVisible.value = false
		}
	}

	function addTrigger(type = 'command') {
		const defaultMatches = {
			command: '/start',
			template_button: '/survey:*',
			inbound_pattern: '*appointment*',
			case_event: 'case.opened',
			schedule: 'daily',
			api: 'external.start',
		}
		flowBuilder.triggers.value.push({
			key: `${type}_${flowBuilder.triggers.value.length + 1}`,
			type,
			match: defaultMatches[type] || '',
			priority: 100,
		})
	}

	function removeTrigger(index) {
		flowBuilder.triggers.value.splice(index, 1)
	}

	function addPaletteNode(type) {
		flowBuilder.addNodeFromPalette(type)
		paletteVisible.value = false
		if (mobile.value) inspectorVisible.value = true
	}

	async function load() {
		loading.value = true
		try {
			await flowBuilder.load()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Flow not loaded',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			loading.value = false
			await nextTick()
			labelCanvasControls()
		}
	}

	function labelCanvasControls() {
		const labels = {
			'.vue-flow__controls-zoomin': 'Zoom in',
			'.vue-flow__controls-zoomout': 'Zoom out',
			'.vue-flow__controls-fitview': 'Fit flow to view',
			'.vue-flow__controls-interactive': 'Toggle flow editing',
		}
		for (const [selector, label] of Object.entries(labels)) {
			const control = canvas.value?.querySelector(selector)
			if (control) {
				control.setAttribute('aria-label', label)
				control.setAttribute('title', label)
			}
		}
	}

	watch(
		() => flowBuilder.selected.value,
		(selected) => {
			if (mobile.value && selected) inspectorVisible.value = true
		},
	)

	onMounted(() => {
		updateViewport()
		window.addEventListener('resize', updateViewport)
		load()
	})
	onUnmounted(() => window.removeEventListener('resize', updateViewport))
</script>

<template>
	<div class="flow-builder-page">
		<FlowToolbar
			:flow="flowBuilder.flow.value"
			:saving="flowBuilder.saving.value"
			:validating="flowBuilder.validating.value"
			:publishing="flowBuilder.publishing.value"
			:requesting="flowBuilder.requesting.value"
			:can-manage="flowBuilder.flow.value.can_manage"
			@back="router.push({ name: 'flows', query: { flow_type: 'automation' } })"
			@open-triggers="triggerDrawerVisible = true"
			@arrange="flowBuilder.arrange"
			@save="flowBuilder.save()"
			@validate="flowBuilder.validate"
			@publish="flowBuilder.publish"
			@request-approval="flowBuilder.requestApproval"
		/>

		<div v-if="mobile" class="mobile-builder-actions">
			<Button label="Add step" severity="secondary" outlined @click="paletteVisible = true">
				<template #icon><ListTree :size="15" /></template>
			</Button>
			<Button
				label="Step settings"
				severity="secondary"
				outlined
				:disabled="!flowBuilder.selected.value"
				@click="inspectorVisible = true"
			>
				<template #icon><PanelRight :size="15" /></template>
			</Button>
		</div>

		<div class="flow-builder-grid" :class="{ mobile }">
			<FlowPalette v-if="!mobile" @add="addPaletteNode" />

			<main
				ref="canvas"
				class="flow-canvas"
				@dragover.prevent
				@drop="flowBuilder.addNodeFromDrop"
			>
				<div v-if="loading" class="canvas-loading">
					<Sparkles :size="22" />
					<strong>Preparing visual flow…</strong>
				</div>
				<VueFlow
					v-else
					v-model:nodes="flowBuilder.nodes.value"
					v-model:edges="flowBuilder.edges.value"
					:delete-key-code="null"
					:min-zoom="0.2"
					:max-zoom="1.8"
					fit-view-on-init
				>
					<Background pattern-color="var(--wa-border-strong)" :gap="20" />
					<Controls position="bottom-left" />
					<template #node-core="nodeProperties">
						<FlowNode :data="nodeProperties.data" />
					</template>
				</VueFlow>
			</main>

			<FlowInspector
				v-if="!mobile"
				:selected-node="flowBuilder.selectedNode.value"
				:selected-edge="flowBuilder.selectedEdge.value"
				:choice-options-text="flowBuilder.choiceOptionsText.value"
				:actions="flowBuilder.catalog.value.actions"
				:templates="flowBuilder.catalog.value.templates"
				:meta-flows="flowBuilder.catalog.value.meta_flows"
				@update:choice-options-text="flowBuilder.choiceOptionsText.value = $event"
				@delete="flowBuilder.deleteSelected"
				@ensure-condition="flowBuilder.ensureEdgeCondition"
			/>
		</div>
	</div>

	<Drawer v-model:visible="paletteVisible" header="Add a flow step" position="left">
		<FlowPalette class="drawer-panel" @add="addPaletteNode" />
	</Drawer>
	<Drawer v-model:visible="inspectorVisible" header="Step settings" position="right">
		<FlowInspector
			class="drawer-panel"
			:selected-node="flowBuilder.selectedNode.value"
			:selected-edge="flowBuilder.selectedEdge.value"
			:choice-options-text="flowBuilder.choiceOptionsText.value"
			:actions="flowBuilder.catalog.value.actions"
			:templates="flowBuilder.catalog.value.templates"
			:meta-flows="flowBuilder.catalog.value.meta_flows"
			@update:choice-options-text="flowBuilder.choiceOptionsText.value = $event"
			@delete="flowBuilder.deleteSelected"
			@ensure-condition="flowBuilder.ensureEdgeCondition"
		/>
	</Drawer>
	<FlowTriggerDrawer
		v-model:visible="triggerDrawerVisible"
		:triggers="flowBuilder.triggers.value"
		@add="addTrigger"
		@remove="removeTrigger"
	/>
</template>

<style scoped>
	.flow-builder-page {
		height: calc(100dvh - 56px);
		min-height: 520px;
		overflow: hidden;
		background: var(--wa-bg);
	}
	.flow-builder-grid {
		height: calc(100% - 66px);
		display: grid;
		grid-template-columns: 205px minmax(420px, 1fr) 310px;
	}
	.flow-builder-grid.mobile {
		height: calc(100% - 122px);
		display: block;
	}
	.flow-canvas {
		position: relative;
		min-width: 0;
		height: 100%;
		overflow: hidden;
		background: var(--wa-surface-muted);
	}
	.canvas-loading {
		position: absolute;
		inset: 0;
		display: grid;
		place-content: center;
		justify-items: center;
		gap: 10px;
		color: var(--wa-muted);
	}
	.canvas-loading strong {
		color: var(--wa-text);
		font-size: 13px;
	}
	.mobile-builder-actions {
		height: 56px;
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 12px;
		border-bottom: 1px solid var(--wa-border);
		background: var(--wa-surface);
	}
	.drawer-panel {
		height: 100%;
		padding: 0;
		border: 0;
	}
	:deep(.vue-flow) {
		background: var(--wa-surface-muted);
	}
	:deep(.vue-flow__controls) {
		overflow: hidden;
		border: 1px solid var(--wa-border);
		border-radius: 9px;
		box-shadow: var(--wa-shadow-sm);
	}
	:deep(.vue-flow__controls-button) {
		color: var(--wa-text);
		border-color: var(--wa-border);
		background: var(--wa-surface);
	}
	@media (max-width: 1180px) and (min-width: 900px) {
		.flow-builder-grid {
			grid-template-columns: 175px minmax(360px, 1fr) 280px;
		}
	}
	@media (max-width: 899px) {
		.flow-builder-page {
			min-height: 460px;
		}
	}
</style>
