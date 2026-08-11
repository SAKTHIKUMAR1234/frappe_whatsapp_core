<script setup>
	import Button from 'primevue/button'
	import ProgressSpinner from 'primevue/progressspinner'
	import { AlertTriangle, Inbox } from 'lucide-vue-next'

	defineProps({
		loading: { type: Boolean, default: false },
		error: { type: String, default: '' },
		empty: { type: Boolean, default: false },
		loadingLabel: { type: String, default: 'Loading workspace…' },
		emptyTitle: { type: String, default: 'Nothing here yet' },
		emptyMessage: { type: String, default: 'New records will appear here automatically.' },
	})

	defineEmits(['retry'])
</script>

<template>
	<section v-if="loading" class="async-state" aria-live="polite" aria-busy="true">
		<ProgressSpinner stroke-width="5" />
		<div>
			<strong>{{ loadingLabel }}</strong
			><span>Please wait while we fetch the latest data.</span>
		</div>
	</section>
	<section v-else-if="error" class="async-state error" role="alert">
		<span class="state-icon"><AlertTriangle :size="21" /></span>
		<div>
			<strong>We could not load this workspace</strong><span>{{ error }}</span>
		</div>
		<Button label="Try again" outlined size="small" @click="$emit('retry')" />
	</section>
	<section v-else-if="empty" class="async-state empty">
		<span class="state-icon"><Inbox :size="21" /></span>
		<div>
			<strong>{{ emptyTitle }}</strong
			><span>{{ emptyMessage }}</span>
		</div>
		<slot />
	</section>
</template>

<style scoped>
	.async-state {
		min-height: 190px;
		padding: 28px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 14px;
		border: 1px dashed var(--wa-border-soft);
		border-radius: 16px;
		background: rgb(255 255 255 / 72%);
		text-align: left;
	}
	.async-state :deep(.p-progressspinner) {
		width: 30px;
		height: 30px;
		color: var(--wa-primary);
	}
	.async-state > div {
		display: grid;
		gap: 4px;
	}
	.async-state strong {
		font-size: 14px;
	}
	.async-state span:not(.state-icon) {
		max-width: 520px;
		color: var(--wa-muted);
		font-size: 13px;
		line-height: 1.5;
	}
	.state-icon {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		flex: 0 0 40px;
		border-radius: 12px;
		color: var(--wa-primary);
		background: var(--wa-mint);
	}
	.async-state.error {
		border-style: solid;
		border-color: #f4cbc6;
		background: var(--wa-danger-soft);
	}
	.error .state-icon {
		color: var(--wa-danger);
		background: var(--wa-surface);
	}
	.async-state > .p-button {
		margin-left: 10px;
	}
	@media (max-width: 600px) {
		.async-state {
			min-height: 170px;
			padding: 24px 18px;
			flex-direction: column;
			text-align: center;
		}
		.async-state > .p-button {
			width: 100%;
			margin: 4px 0 0;
		}
	}
</style>
