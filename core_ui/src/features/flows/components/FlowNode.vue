<script setup>
	import { computed } from 'vue'
	import { Handle, Position } from '@vue-flow/core'
	import {
		Bot,
		CircleStop,
		GitBranch,
		Hand,
		MessageSquareText,
		MousePointerClick,
		Play,
		Send,
		Timer,
		Zap,
	} from 'lucide-vue-next'

	const props = defineProps({ data: Object })
	const styles = {
		start: ['#087457', '#def8ed', Play],
		send_template: ['#0f766e', '#dff7f4', Send],
		send_message: ['#147d65', '#e0f6ee', MessageSquareText],
		ask_text: ['#2859bf', '#e7efff', Bot],
		ask_choice: ['#5542c2', '#eeebff', MousePointerClick],
		condition: ['#b16814', '#fff2dd', GitBranch],
		action: ['#873db3', '#f4e9fb', Zap],
		wait: ['#56636f', '#eaf0f3', Timer],
		human_handoff: ['#be3f62', '#ffebf1', Hand],
		end: ['#9e3030', '#ffebeb', CircleStop],
	}
	const style = computed(() => styles[props.data.type] || styles.action)
</script>

<template>
	<div class="node" :style="{ borderColor: style[0] }">
		<Handle v-if="data.type !== 'start'" type="target" :position="Position.Left" />
		<div class="icon" :style="{ background: style[1], color: style[0] }">
			<component :is="style[2]" :size="15" />
		</div>
		<div>
			<span :style="{ color: style[0] }">{{ data.type.replaceAll('_', ' ') }}</span
			><strong>{{ data.config?.label || data.type }}</strong>
		</div>
		<Handle
			v-if="!['end', 'human_handoff'].includes(data.type)"
			type="source"
			:position="Position.Right"
		/>
	</div>
</template>

<style scoped>
	.node {
		min-width: 168px;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 11px 12px;
		border: 1.5px solid;
		border-radius: 13px;
		background: white;
		box-shadow: 0 6px 18px #12251e10;
	}
	.icon {
		width: 31px;
		height: 31px;
		display: grid;
		place-items: center;
		border-radius: 9px;
	}
	.node span,
	.node strong {
		display: block;
	}
	.node span {
		text-transform: uppercase;
		letter-spacing: 0.08em;
		font-size: 7px;
		font-weight: 800;
	}
	.node strong {
		max-width: 110px;
		margin-top: 3px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: #203029;
		font-size: 10px;
	}
	.vue-flow__node.selected .node {
		outline: 3px solid #29ad7d2f;
		outline-offset: 3px;
	}
</style>
