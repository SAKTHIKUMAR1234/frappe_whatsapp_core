<script setup>
	import { computed } from 'vue'
	import { CheckCircle2, LayoutTemplate, PanelTop } from 'lucide-vue-next'
	import { describeFlowAsset } from '@/features/flows/utils/flowAsset'

	const props = defineProps({
		asset: { type: Object, default: null },
	})
	const overview = computed(() => describeFlowAsset(props.asset))
</script>

<template>
	<div v-if="overview.screenCount" class="asset-overview">
		<div class="asset-metrics">
			<div>
				<LayoutTemplate :size="18" /><span>Screens</span
				><strong>{{ overview.screenCount }}</strong>
			</div>
			<div>
				<PanelTop :size="18" /><span>Components</span
				><strong>{{ overview.componentCount }}</strong>
			</div>
		</div>
		<div class="screen-list" aria-label="Flow screens">
			<article v-for="(screen, index) in overview.screens" :key="screen.id">
				<span>{{ index + 1 }}</span>
				<div>
					<strong>{{ screen.title }}</strong
					><small>{{ screen.id }}</small>
				</div>
				<em v-if="screen.terminal"><CheckCircle2 :size="13" />Final screen</em>
			</article>
		</div>
	</div>
	<div v-else class="asset-empty">
		<LayoutTemplate :size="25" />
		<strong>No Flow asset uploaded yet</strong>
		<span>Open the advanced editor to add a Meta flow.json document.</span>
	</div>
</template>

<style scoped>
	.asset-overview {
		display: grid;
		gap: 16px;
	}
	.asset-metrics {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}
	.asset-metrics > div {
		display: grid;
		grid-template-columns: 28px 1fr auto;
		align-items: center;
		gap: 8px;
		padding: 12px;
		border: 1px solid var(--wa-border-soft);
		border-radius: 10px;
		background: var(--wa-surface-muted);
	}
	.asset-metrics svg {
		color: var(--wa-primary);
	}
	.asset-metrics span {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.asset-metrics strong {
		font-size: 18px;
	}
	.screen-list {
		display: grid;
		gap: 8px;
	}
	.screen-list article {
		display: grid;
		grid-template-columns: 30px minmax(0, 1fr) auto;
		align-items: center;
		gap: 10px;
		padding: 10px;
		border: 1px solid var(--wa-border-soft);
		border-radius: 10px;
		background: var(--wa-surface);
	}
	.screen-list article > span {
		width: 28px;
		height: 28px;
		display: grid;
		place-items: center;
		border-radius: 8px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		font-size: 11px;
		font-weight: 800;
	}
	.screen-list div {
		min-width: 0;
		display: grid;
		gap: 2px;
	}
	.screen-list strong,
	.screen-list small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.screen-list strong {
		font-size: 12px;
	}
	.screen-list small {
		color: var(--wa-muted);
		font-size: 10px;
	}
	.screen-list em {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		color: var(--wa-success);
		font-size: 10px;
		font-style: normal;
		font-weight: 700;
	}
	.asset-empty {
		min-height: 220px;
		display: grid;
		place-content: center;
		justify-items: center;
		gap: 7px;
		color: var(--wa-muted);
		text-align: center;
	}
	.asset-empty strong {
		color: var(--wa-text);
		font-size: 13px;
	}
	.asset-empty span {
		max-width: 340px;
		font-size: 12px;
		line-height: 1.5;
	}
	@media (max-width: 560px) {
		.asset-metrics {
			grid-template-columns: 1fr;
		}
		.screen-list article {
			grid-template-columns: 30px minmax(0, 1fr);
		}
		.screen-list em {
			grid-column: 2;
		}
	}
</style>
