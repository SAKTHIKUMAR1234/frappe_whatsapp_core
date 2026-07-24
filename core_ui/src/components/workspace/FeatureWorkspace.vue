<script setup>
	import Button from 'primevue/button'
	import Tag from 'primevue/tag'
	import { CheckCircle2, ShieldCheck } from 'lucide-vue-next'

	defineProps({
		definition: {
			type: Object,
			required: true,
		},
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">{{ definition.eyebrow }}</div>
			<h1>{{ definition.title }}</h1>
			<p>{{ definition.description }}</p>
		</div>
		<Button :label="definition.primaryAction" :outlined="definition.readOnly">
			<template #icon>
				<component :is="definition.icon" :size="16" />
			</template>
		</Button>
	</div>

	<div v-if="definition.readOnly" class="ownership-note">
		<ShieldCheck :size="17" />
		<div>
			<strong>Read-only in Core</strong>
			<span>
				Creation, Meta submission, editing, site assignment and enable/disable are owned by
				the Frappe WhatsApp Integration Desk.
			</span>
		</div>
	</div>

	<section class="summary-grid">
		<div
			v-for="metric in definition.metrics"
			:key="metric.label"
			class="surface-card summary-card"
		>
			<span>{{ metric.label }}</span>
			<strong>{{ metric.value }}</strong>
			<small>{{ metric.detail }}</small>
		</div>
	</section>

	<section class="surface-card workspace-empty">
		<div class="module-icon">
			<component :is="definition.icon" :size="26" />
		</div>
		<Tag value="Site-local configuration" severity="success" rounded />
		<h2>{{ definition.title }} workspace</h2>
		<p>Configuration and records for this module remain inside the current company site.</p>
		<div class="rules">
			<span><CheckCircle2 :size="14" />Role controlled</span>
			<span><CheckCircle2 :size="14" />Fully audited</span>
			<span><CheckCircle2 :size="14" />Tenant isolated</span>
		</div>
	</section>
</template>

<style scoped>
	.ownership-note {
		display: flex;
		align-items: flex-start;
		gap: 11px;
		padding: 13px 15px;
		margin: -7px 0 18px;
		border: 1px solid #bae7d4;
		border-radius: 12px;
		color: #0d664b;
		background: #ebfaf4;
	}

	.ownership-note strong,
	.ownership-note span {
		display: block;
	}

	.ownership-note strong {
		font-size: 11px;
	}

	.ownership-note span {
		margin-top: 3px;
		font-size: 9px;
	}

	.summary-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 14px;
		margin-bottom: 18px;
	}

	.summary-card {
		padding: 19px;
	}

	.summary-card span,
	.summary-card strong,
	.summary-card small {
		display: block;
	}

	.summary-card span {
		color: #718078;
		font-size: 10px;
	}

	.summary-card strong {
		margin: 7px 0 3px;
		font-size: 24px;
	}

	.summary-card small {
		color: #98a19c;
		font-size: 9px;
	}

	.workspace-empty {
		min-height: 390px;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		text-align: center;
	}

	.module-icon {
		width: 58px;
		height: 58px;
		display: grid;
		place-items: center;
		margin-bottom: 15px;
		border-radius: 18px;
		color: #087457;
		background: #ddf7ec;
	}

	.workspace-empty h2 {
		margin: 15px 0 5px;
		font-size: 18px;
	}

	.workspace-empty p {
		margin: 0;
		color: #78867f;
		font-size: 11px;
	}

	.rules {
		display: flex;
		gap: 17px;
		margin-top: 23px;
		color: #4f645a;
		font-size: 9px;
	}

	.rules span {
		display: flex;
		align-items: center;
		gap: 5px;
	}

	@media (max-width: 800px) {
		.summary-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
