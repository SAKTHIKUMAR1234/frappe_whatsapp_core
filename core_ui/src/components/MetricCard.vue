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
			<small>{{ detail }}</small>
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
		border-radius: 17px;
		background: white;
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
		color: #6e7c75;
		font-size: 11px;
		font-weight: 600;
	}
	.metric-copy strong {
		margin: 7px 0 3px;
		font-size: 28px;
		letter-spacing: -0.8px;
	}
	.metric-copy small {
		color: #8b9791;
		font-size: 9px;
	}
	.green .metric-icon {
		background: #ddf8eb;
		color: #087354;
	}
	.blue .metric-icon {
		background: #e5efff;
		color: #2b61c9;
	}
	.orange .metric-icon {
		background: #fff0da;
		color: #bf6617;
	}
	.purple .metric-icon {
		background: #f0e8ff;
		color: #7540ba;
	}
</style>
