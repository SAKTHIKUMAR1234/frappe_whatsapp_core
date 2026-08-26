<script setup>
	defineProps({
		label: String,
		value: [String, Number],
		detail: String,
		icon: Object,
		tone: { type: String, default: 'green' },
	})
</script>

<template>
	<div :class="['metric-card', tone]">
		<div class="metric-icon"><component :is="icon" :size="20" /></div>
		<div class="metric-copy">
			<span>{{ label }}</span>
			<strong>{{ value }}</strong>
			<small v-if="detail">{{ detail }}</small>
		</div>
	</div>
</template>

<style scoped>
	.metric-card {
		display: flex;
		gap: 15px;
		padding: 20px;
		min-height: 128px;
		border: 1px solid var(--wa-border);
		border-radius: 8px;
		background: var(--wa-surface);
	}
	.metric-icon {
		display: grid;
		place-items: center;
		width: 43px;
		height: 43px;
		border-radius: 13px;
		flex: none;
	}
	.metric-copy span,
	.metric-copy strong,
	.metric-copy small {
		display: block;
	}
	.metric-copy span {
		color: var(--wa-muted);
		font-size: 11px;
		font-weight: 600;
	}
	.metric-copy strong {
		margin: 7px 0 3px;
		font-size: 28px;
		letter-spacing: -0.8px;
	}
	.metric-copy small {
		color: var(--wa-muted);
		font-size: 12px;
	}
	.green .metric-icon {
		background: var(--wa-success-soft);
		color: var(--wa-success);
	}
	.blue .metric-icon {
		background: color-mix(in srgb, var(--wa-primary) 14%, var(--wa-surface));
		color: var(--wa-primary);
	}
	.orange .metric-icon {
		background: var(--wa-warning-soft);
		color: var(--wa-warning);
	}
	.purple .metric-icon {
		background: color-mix(in srgb, #8756c5 16%, var(--wa-surface));
		color: color-mix(in srgb, #8756c5 78%, var(--wa-text));
	}
</style>
