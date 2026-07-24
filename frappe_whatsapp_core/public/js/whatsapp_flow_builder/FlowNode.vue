<script setup>
import { Handle, Position } from "@vue-flow/core";
import { computed } from "vue";

const props = defineProps({ data: Object });
const colors = {
	start: "#166534",
	end: "#991b1b",
	send_template: "#075e54",
	send_message: "#0f766e",
	ask_text: "#1d4ed8",
	ask_choice: "#4338ca",
	condition: "#a16207",
	action: "#7e22ce",
	wait: "#475569",
	human_handoff: "#be123c",
};
const color = computed(() => colors[props.data.type] || "#334155");
</script>

<template>
	<div class="flow-node" :style="{ borderColor: color }">
		<Handle v-if="data.type !== 'start'" type="target" :position="Position.Left" />
		<div class="node-type" :style="{ color }">{{ __(data.type.replaceAll("_", " ")) }}</div>
		<div class="node-label">{{ __(data.label || data.type) }}</div>
		<Handle
			v-if="!['end', 'human_handoff'].includes(data.type)"
			type="source"
			:position="Position.Right"
		/>
	</div>
</template>

<style scoped>
.flow-node {
	min-width: 150px;
	max-width: 220px;
	padding: 12px 16px;
	border: 2px solid;
	border-radius: 12px;
	background: var(--fg-color);
	box-shadow: var(--shadow-sm);
}
.node-type {
	font-size: 10px;
	font-weight: 700;
	letter-spacing: 0.08em;
	text-transform: uppercase;
}
.node-label {
	margin-top: 4px;
	font-size: 13px;
	font-weight: 600;
	color: var(--text-color);
}
</style>
