<script setup>
	import {
		CircleStop,
		GitBranch,
		Hand,
		ListChecks,
		ListPlus,
		MessageSquareText,
		MousePointerClick,
		Send,
		Timer,
		TextCursorInput,
		Zap,
	} from 'lucide-vue-next'
	import { NODE_TYPES } from '@/features/flows/domain/nodeTypes'

	const icons = {
		send: Send,
		flow: ListChecks,
		message: MessageSquareText,
		text: ListPlus,
		choice: MousePointerClick,
		input: TextCursorInput,
		branch: GitBranch,
		action: Zap,
		wait: Timer,
		handoff: Hand,
		end: CircleStop,
	}

	defineEmits(['add'])

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
			@click="$emit('add', nodeType.type)"
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
		background: var(--wa-surface);
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
		color: var(--wa-muted);
		font-size: 12px;
	}

	button {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 8px;
		margin: 5px 0;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		color: var(--wa-text);
		background: var(--wa-surface-muted);
		cursor: grab;
		font-size: 12px;
		font-weight: 650;
		text-align: left;
	}

	button span {
		width: 27px;
		height: 27px;
		display: grid;
		place-items: center;
		border-radius: 8px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}

	button:hover,
	button:focus-visible {
		border-color: color-mix(in srgb, var(--wa-success) 45%, var(--wa-border));
		background: var(--wa-success-soft);
		outline: 0;
	}
</style>
