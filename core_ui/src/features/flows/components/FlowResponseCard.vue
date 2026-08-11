<script setup>
	import { computed } from 'vue'
	import { CheckCircle2, ClipboardCheck } from 'lucide-vue-next'
	import { flowResponseFields, parseFlowValue } from '@/features/flows/utils/flowResponse'

	const props = defineProps({
		response: { type: [Object, Array, String], default: null },
		heading: { type: String, default: 'Flow response' },
		subtitle: { type: String, default: '' },
		status: { type: String, default: 'Submitted' },
		compact: { type: Boolean, default: false },
	})

	const parsed = computed(() => parseFlowValue(props.response))
	const fields = computed(() => flowResponseFields(parsed.value))
</script>

<template>
	<section :class="['flow-response-card', { compact }]">
		<header>
			<span class="flow-icon"><ClipboardCheck :size="17" /></span>
			<div class="flow-title">
				<strong>{{ heading }}</strong>
				<small v-if="subtitle">{{ subtitle }}</small>
			</div>
			<span class="flow-status"><CheckCircle2 :size="13" />{{ status }}</span>
		</header>
		<dl v-if="fields.length">
			<div v-for="field in fields" :key="field.key" class="flow-answer">
				<dt>{{ field.label }}</dt>
				<dd>{{ field.value }}</dd>
			</div>
		</dl>
		<p v-else class="flow-empty">Response received</p>
	</section>
</template>

<style scoped>
	.flow-response-card {
		width: min(380px, 100%);
		overflow: hidden;
		border: 1px solid color-mix(in srgb, var(--wa-primary) 24%, var(--wa-border));
		border-radius: 10px;
		background: color-mix(in srgb, var(--wa-surface) 88%, transparent);
	}
	header {
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 9px 10px;
		border-bottom: 1px solid var(--wa-border);
	}
	.flow-icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		flex: 0 0 30px;
		border-radius: 8px;
		color: var(--wa-primary);
		background: color-mix(in srgb, var(--wa-primary) 12%, transparent);
	}
	.flow-title {
		display: grid;
		min-width: 0;
		margin-right: auto;
	}
	.flow-title strong {
		overflow: hidden;
		color: var(--wa-text);
		font-size: 12px;
		font-weight: 700;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.flow-title small {
		overflow: hidden;
		color: var(--wa-muted);
		font-size: 10px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.flow-status {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		padding: 3px 6px;
		border-radius: 999px;
		color: var(--wa-success);
		background: color-mix(in srgb, var(--wa-success) 10%, transparent);
		font-size: 10px;
		font-weight: 700;
		white-space: nowrap;
	}
	dl {
		display: grid;
		gap: 0;
		margin: 0;
	}
	.flow-answer {
		display: grid;
		grid-template-columns: minmax(90px, 0.7fr) minmax(120px, 1fr);
		gap: 10px;
		padding: 7px 10px;
		border-bottom: 1px solid color-mix(in srgb, var(--wa-border) 70%, transparent);
	}
	.flow-answer:last-child {
		border-bottom: 0;
	}
	dt,
	dd {
		margin: 0;
		font-size: 11px;
		line-height: 1.35;
		overflow-wrap: anywhere;
	}
	dt {
		color: var(--wa-muted);
	}
	dd {
		color: var(--wa-text);
		font-weight: 600;
	}
	.flow-empty {
		margin: 0;
		padding: 9px 10px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.compact {
		min-width: 260px;
	}
	.compact header {
		padding: 7px 8px;
	}
	.compact .flow-answer {
		padding: 6px 8px;
	}
	@media (max-width: 540px) {
		.flow-response-card {
			width: 100%;
		}
		.flow-answer {
			grid-template-columns: 1fr;
			gap: 2px;
		}
	}
</style>
