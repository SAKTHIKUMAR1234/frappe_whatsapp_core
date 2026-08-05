<script setup>
	import { onMounted, ref } from 'vue'
	import { useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import { Activity, GitBranch, ListChecks, MessageCircleQuestion } from 'lucide-vue-next'

	import { call } from '@/services/frappe'

	const router = useRouter()
	const loading = ref(true)
	const workspace = ref({ flows: [], metrics: {} })

	onMounted(async () => {
		try {
			workspace.value = await call('frappe_whatsapp_core.frontend_api.polls_workspace')
		} finally {
			loading.value = false
		}
	})

	function statusSeverity(status) {
		if (status === 'Published') return 'success'
		if (status === 'Retired') return 'danger'
		return 'warn'
	}
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Structured collection</div>
			<h1>Polls & Forms</h1>
			<p>
				Questions are versioned flow nodes, so branching and typed actions use one engine.
			</p>
		</div>
		<Button label="Build a question flow" @click="router.push({ name: 'flows' })">
			<template #icon><GitBranch :size="16" /></template>
		</Button>
	</div>

	<section class="summary-grid">
		<article class="surface-card">
			<MessageCircleQuestion :size="19" />
			<div>
				<small>Drafts</small><strong>{{ workspace.metrics.drafts || 0 }}</strong>
			</div>
		</article>
		<article class="surface-card">
			<Activity :size="19" />
			<div>
				<small>Active</small><strong>{{ workspace.metrics.active || 0 }}</strong>
			</div>
		</article>
		<article class="surface-card">
			<ListChecks :size="19" />
			<div>
				<small>Completed answers</small
				><strong>{{ workspace.metrics.responses || 0 }}</strong>
			</div>
		</article>
	</section>

	<div class="engine-note">
		<GitBranch :size="18" />
		<div>
			<strong>One configurable engine</strong>
			<span
				>Text questions, buttons, lists, validation, branches, waits and business actions
				are built in Flow Builder.</span
			>
		</div>
	</div>

	<section class="surface-card poll-table">
		<div v-if="loading" class="loading">
			<Skeleton v-for="index in 5" :key="index" height="58px" />
		</div>
		<DataTable v-else :value="workspace.flows" striped-rows>
			<Column header="Question flow">
				<template #body="{ data }">
					<button
						class="flow-name"
						@click="
							router.push({ name: 'flow-builder', params: { flowName: data.name } })
						"
					>
						<span><MessageCircleQuestion :size="17" /></span>
						<div>
							<strong>{{ data.title }}</strong
							><small>{{ data.flow_key }}</small>
						</div>
					</button>
				</template>
			</Column>
			<Column field="question_count" header="Questions" />
			<Column field="choice_count" header="Choice nodes" />
			<Column field="active_version" header="Active version">
				<template #body="{ data }">{{ data.active_version || '—' }}</template>
			</Column>
			<Column field="status" header="Status">
				<template #body="{ data }">
					<Tag :value="data.status" :severity="statusSeverity(data.status)" rounded />
				</template>
			</Column>
			<Column field="modified" header="Updated" />
			<template #empty>
				<div class="empty">
					<MessageCircleQuestion :size="30" />
					<strong>No question flows yet</strong>
					<span>Add an Ask Text or Ask Choice node in Flow Builder.</span>
				</div>
			</template>
		</DataTable>
	</section>
</template>

<style scoped>
	.summary-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 16px;
	}

	.summary-grid article {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 17px;
		color: #17805f;
	}

	.summary-grid small,
	.summary-grid strong {
		display: block;
	}

	.summary-grid small {
		color: var(--wa-muted);
		font-size: 9px;
	}

	.summary-grid strong {
		margin-top: 4px;
		color: #17211d;
		font-size: 20px;
	}

	.engine-note {
		display: flex;
		align-items: center;
		gap: 11px;
		padding: 13px 16px;
		margin-bottom: 16px;
		border: 1px solid #cfe9df;
		border-radius: 14px;
		color: #147154;
		background: #edf9f4;
	}

	.engine-note strong,
	.engine-note span {
		display: block;
	}

	.engine-note span {
		margin-top: 3px;
		color: #56736a;
		font-size: 9px;
	}

	.poll-table {
		overflow: hidden;
	}

	.flow-name {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 0;
		border: 0;
		text-align: left;
		background: transparent;
		cursor: pointer;
	}

	.flow-name > span {
		display: grid;
		place-items: center;
		width: 35px;
		height: 35px;
		border-radius: 10px;
		color: #087255;
		background: #e3f7ef;
	}

	.flow-name strong,
	.flow-name small {
		display: block;
	}

	.flow-name strong {
		font-size: 11px;
	}

	.flow-name small {
		margin-top: 3px;
		color: #89958f;
		font-size: 8px;
	}

	@media (max-width: 760px) {
		.summary-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
