<script setup>
	import { onMounted, ref } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import { Background } from '@vue-flow/background'
	import { Controls } from '@vue-flow/controls'
	import { VueFlow } from '@vue-flow/core'
	import { useToast } from 'primevue/usetoast'

	import FlowInspector from '@/features/flows/components/FlowInspector.vue'
	import FlowNode from '@/features/flows/components/FlowNode.vue'
	import FlowPalette from '@/features/flows/components/FlowPalette.vue'
	import FlowToolbar from '@/features/flows/components/FlowToolbar.vue'
	import FlowTriggerDrawer from '@/features/flows/components/FlowTriggerDrawer.vue'
	import { useFlowBuilder } from '@/features/flows/composables/useFlowBuilder'

	const route = useRoute()
	const router = useRouter()
	const toast = useToast()
	const triggerDrawerVisible = ref(false)

	const flowBuilder = useFlowBuilder({
		flowName: route.params.flowName,
		toast,
	})

	function addCommandTrigger() {
		flowBuilder.triggers.value.push({
			key: `command_${flowBuilder.triggers.value.length + 1}`,
			type: 'command',
			match: '/help',
			priority: 100,
		})
	}

	function removeTrigger(index) {
		flowBuilder.triggers.value.splice(index, 1)
	}

	onMounted(flowBuilder.load)
</script>

<template>
	<div class="flow-builder-page">
		<FlowToolbar
			:flow="flowBuilder.flow.value"
			:saving="flowBuilder.saving.value"
			:validating="flowBuilder.validating.value"
			:publishing="flowBuilder.publishing.value"
			@back="router.push({ name: 'flows' })"
			@open-triggers="triggerDrawerVisible = true"
			@save="flowBuilder.save()"
			@validate="flowBuilder.validate"
			@publish="flowBuilder.publish"
		/>

		<div class="flow-builder-grid">
			<FlowPalette />

			<main class="flow-canvas" @dragover.prevent @drop="flowBuilder.addNodeFromDrop">
				<VueFlow
					v-model:nodes="flowBuilder.nodes.value"
					v-model:edges="flowBuilder.edges.value"
					:delete-key-code="null"
				>
					<Background pattern-color="#d7e1dc" :gap="20" />
					<Controls position="bottom-left" />
					<template #node-core="nodeProperties">
						<FlowNode :data="nodeProperties.data" />
					</template>
				</VueFlow>
			</main>

			<FlowInspector
				:selected-node="flowBuilder.selectedNode.value"
				:selected-edge="flowBuilder.selectedEdge.value"
				:choice-options-text="flowBuilder.choiceOptionsText.value"
				@update:choice-options-text="flowBuilder.choiceOptionsText.value = $event"
				@delete="flowBuilder.deleteSelected"
				@ensure-condition="flowBuilder.ensureEdgeCondition"
			/>
		</div>
	</div>

	<FlowTriggerDrawer
		v-model:visible="triggerDrawerVisible"
		:triggers="flowBuilder.triggers.value"
		@add="addCommandTrigger"
		@remove="removeTrigger"
	/>
</template>

<style scoped>
	.flow-builder-page {
		height: calc(100vh - 128px);
		margin: -30px;
	}

	.flow-builder-grid {
		height: calc(100% - 66px);
		display: grid;
		grid-template-columns: 205px minmax(420px, 1fr) 290px;
	}

	.flow-canvas {
		min-width: 0;
		background: #f9fbfa;
	}

	@media (max-width: 1050px) {
		.flow-builder-grid {
			grid-template-columns: 175px 1fr;
		}

		:deep(.flow-inspector) {
			position: fixed;
			top: 134px;
			right: 0;
			bottom: 0;
			z-index: 10;
			width: 290px;
			box-shadow: -10px 0 30px rgb(16 39 31 / 9%);
		}
	}
</style>
