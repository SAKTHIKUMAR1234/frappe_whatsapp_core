<script setup>
	import {
		CircleStop,
		GitBranch,
		Hand,
		ListPlus,
		MessageSquareText,
		MousePointerClick,
		Send,
		Timer,
		Zap,
	} from 'lucide-vue-next'
	import { NODE_TYPES } from '@/features/flows/domain/nodeTypes'

	const icons = {
		send: Send,
		message: MessageSquareText,
		text: ListPlus,
		choice: MousePointerClick,
		branch: GitBranch,
		action: Zap,
		wait: Timer,
		handoff: Hand,
		end: CircleStop,
	}

	function startDrag(event, nodeType) {
		event.dataTransfer.setData('application/core-flow', nodeType)
		event.dataTransfer.effectAllowed = 'move'
	}
</script>

<template>
	<aside class="flow-palette">
		<div class="panel-heading">
			<span>Nodes</span>
			<small>Drag to canvas</small>
		</div>

		<button
			v-for="nodeType in NODE_TYPES"
			:key="nodeType.type"
			draggable="true"
			type="button"
			@dragstart="startDrag($event, nodeType.type)"
		>
			<span>
				<component :is="icons[nodeType.icon]" :size="15" />
			</span>
			{{ nodeType.label }}
		</button>
	</aside>
</template>

<style scoped>
	.flow-palette {
		padding: 15px;
		overflow-y: auto;
		border-right: 1px solid var(--wa-border);
		background: white;
	}

	.panel-heading {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 13px;
	}

	.panel-heading span {
		font-size: 11px;
		font-weight: 800;
	}

	.panel-heading small {
		color: #87948e;
		font-size: 8px;
	}

	button {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 8px;
		margin: 5px 0;
		border: 1px solid #e2e9e5;
		border-radius: 10px;
		color: #33433c;
		background: #f8faf9;
		cursor: grab;
		font-size: 10px;
		font-weight: 650;
		text-align: left;
	}

	button span {
		width: 27px;
		height: 27px;
		display: grid;
		place-items: center;
		border-radius: 8px;
		color: #087457;
		background: #e1f7ee;
	}
</style>
