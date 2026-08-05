<script setup>
	import { onMounted, ref } from 'vue'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import {
		Activity,
		CircleCheck,
		MessageSquareWarning,
		RefreshCw,
		Workflow,
	} from 'lucide-vue-next'

	import { call } from '@/services/frappe'

	const loading = ref(true)
	const workspace = ref({
		metrics: {},
		components: [],
		recent_failures: [],
	})

	async function load() {
		loading.value = true
		try {
			workspace.value = await call('frappe_whatsapp_core.frontend_api.health_workspace')
		} finally {
			loading.value = false
		}
	}

	function severity(status) {
		if (status === 'Healthy') return 'success'
		if (status === 'Attention') return 'danger'
		return 'secondary'
	}

	onMounted(load)
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Site-local evidence</div>
			<h1>Audit & Health</h1>
			<p>Operational state derived from events, flow runs and message delivery records.</p>
		</div>
		<Button label="Refresh" outlined @click="load">
			<template #icon><RefreshCw :size="16" /></template>
		</Button>
	</div>

	<section class="summary-grid">
		<article class="surface-card">
			<Activity :size="19" />
			<div>
				<small>Pending events</small
				><strong>{{ workspace.metrics.pending_events || 0 }}</strong>
			</div>
		</article>
		<article class="surface-card danger">
			<MessageSquareWarning :size="19" />
			<div>
				<small>Failed events</small
				><strong>{{ workspace.metrics.failed_events || 0 }}</strong>
			</div>
		</article>
		<article class="surface-card danger">
			<Workflow :size="19" />
			<div>
				<small>Failed flow steps</small
				><strong>{{ workspace.metrics.failed_flow_steps || 0 }}</strong>
			</div>
		</article>
		<article class="surface-card danger">
			<MessageSquareWarning :size="19" />
			<div>
				<small>Failed messages</small
				><strong>{{ workspace.metrics.failed_messages || 0 }}</strong>
			</div>
		</article>
	</section>

	<section class="component-grid">
		<article
			v-for="component in workspace.components"
			:key="component.name"
			class="surface-card component-card"
		>
			<CircleCheck v-if="component.status === 'Healthy'" :size="20" />
			<Activity v-else :size="20" />
			<div>
				<strong>{{ component.name }}</strong>
				<small>{{ component.ownership }}</small>
			</div>
			<Tag :value="component.status" :severity="severity(component.status)" rounded />
		</article>
	</section>

	<section class="surface-card failure-card">
		<header>
			<div>
				<div class="eyebrow">Latest first</div>
				<h2>Recent failures</h2>
			</div>
		</header>
		<div v-if="loading" class="loading">
			<Skeleton v-for="index in 5" :key="index" height="58px" />
		</div>
		<DataTable v-else :value="workspace.recent_failures" striped-rows>
			<Column field="source" header="Source">
				<template #body="{ data }">
					<Tag :value="data.source" severity="secondary" rounded />
				</template>
			</Column>
			<Column field="label" header="Operation" />
			<Column field="attempts" header="Attempts">
				<template #body="{ data }">{{ data.attempts || '—' }}</template>
			</Column>
			<Column field="error" header="Error">
				<template #body="{ data }">
					<p class="error-copy">{{ data.error || 'No error detail recorded' }}</p>
				</template>
			</Column>
			<Column field="modified" header="Time" />
			<template #empty>
				<div class="empty">
					<CircleCheck :size="30" />
					<strong>No recorded failures</strong>
					<span>Core processing is clear on this site.</span>
				</div>
			</template>
		</DataTable>
	</section>
</template>

<style scoped>
	.summary-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 16px;
	}

	.summary-grid article,
	.component-card {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 17px;
		color: #17805f;
	}

	.summary-grid article.danger {
		color: #b43c42;
	}

	.summary-grid small,
	.summary-grid strong,
	.component-card small,
	.component-card strong {
		display: block;
	}

	.summary-grid small,
	.component-card small {
		color: var(--wa-muted);
		font-size: 9px;
	}

	.summary-grid strong {
		margin-top: 4px;
		color: #17211d;
		font-size: 20px;
	}

	.component-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 16px;
	}

	.component-card > div {
		flex: 1;
	}

	.component-card strong {
		font-size: 11px;
	}

	.component-card small {
		margin-top: 3px;
	}

	.failure-card {
		overflow: hidden;
	}

	.failure-card header {
		padding: 17px 18px;
		border-bottom: 1px solid var(--wa-border);
	}

	h2 {
		margin: 3px 0 0;
		font-size: 15px;
	}

	.error-copy {
		max-width: 480px;
		margin: 0;
		overflow: hidden;
		color: #a33d43;
		font-size: 9px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	@media (max-width: 980px) {
		.summary-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.component-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
