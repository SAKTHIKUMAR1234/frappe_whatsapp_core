<script setup>
	import { computed, onMounted, reactive, ref } from 'vue'
	import { useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import AppDialog from '@/components/AppDialog.vue'
	import FlowTypeSwitch from '@/features/flows/components/FlowTypeSwitch.vue'
	import InputText from 'primevue/inputtext'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import { GitBranch, Plus, Search, WandSparkles } from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'
	import {
		createAutomationFlow,
		listAutomationFlows,
	} from '@/features/flows/services/automationFlowService'
	import { errorMessage } from '@/services/frappe'
	import { formatDateTime } from '@/utils/datetime'
	import { focusDialogControl } from '@/utils/focus'

	const router = useRouter()
	const toast = useToast()
	const loading = ref(true)
	const creating = ref(false)
	const dialog = ref(false)
	const dialogRef = ref(null)
	const flows = ref([])
	const filter = ref('')
	const form = reactive({ title: '', flow_key: '' })
	const filteredFlows = computed(() => {
		const query = filter.value.trim().toLowerCase()
		if (!query) return flows.value
		return flows.value.filter((flow) =>
			[flow.title, flow.flow_key, flow.status, flow.description]
				.join(' ')
				.toLowerCase()
				.includes(query),
		)
	})

	async function load() {
		loading.value = true
		try {
			flows.value = await listAutomationFlows()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Flows not loaded',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			loading.value = false
		}
	}

	async function createFlow() {
		creating.value = true
		try {
			const name = await createAutomationFlow({
				title: form.title.trim(),
				flow_key: form.flow_key.trim(),
			})
			dialog.value = false
			router.push({ name: 'automation-flow-builder', params: { flowName: name } })
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Flow not created',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			creating.value = false
		}
	}

	function openFlow(flow) {
		router.push({ name: 'automation-flow-builder', params: { flowName: flow.name } })
	}

	function severity(status) {
		return status === 'Published' ? 'success' : status === 'Retired' ? 'danger' : 'warn'
	}

	function approvalSeverity(status) {
		if (status === 'Approved') return 'success'
		if (status === 'Rejected') return 'danger'
		if (status === 'Pending Approval') return 'info'
		return 'secondary'
	}

	onMounted(load)
</script>

<template>
	<FlowTypeSwitch />
	<div class="page-heading">
		<h1>Flow Builder</h1>
		<Button label="Create flow" @click="dialog = true">
			<template #icon><Plus :size="16" /></template>
		</Button>
	</div>

	<section class="surface-card flow-list">
		<div class="list-toolbar">
			<div class="search-box">
				<Search :size="16" />
				<input
					v-model="filter"
					aria-label="Search automation flows"
					placeholder="Search automations…"
				/>
			</div>
			<span>{{ filteredFlows.length }} flows</span>
		</div>
		<div v-if="loading" class="loading">
			<Skeleton v-for="index in 5" :key="index" height="58px" />
		</div>
		<DataTable v-else :value="filteredFlows" striped-rows>
			<Column header="Flow">
				<template #body="{ data }">
					<button class="flow-name" @click="openFlow(data)">
						<span><GitBranch :size="17" /></span>
						<div>
							<strong>{{ data.title }}</strong>
							<small>{{ data.flow_key }}</small>
						</div>
					</button>
				</template>
			</Column>
			<Column field="status" header="Status">
				<template #body="{ data }">
					<Tag :value="data.status" :severity="severity(data.status)" rounded />
				</template>
			</Column>
			<Column field="approval_status" header="Approval">
				<template #body="{ data }">
					<Tag
						:value="data.approval_status || 'Draft'"
						:severity="approvalSeverity(data.approval_status)"
						rounded
					/>
				</template>
			</Column>
			<Column field="active_version" header="Active version">
				<template #body="{ data }">{{ data.active_version || '—' }}</template>
			</Column>
			<Column field="modified" header="Last updated">
				<template #body="{ data }">{{ formatDateTime(data.modified) }}</template>
			</Column>
			<Column>
				<template #body="{ data }">
					<Button
						class="open-flow-action"
						icon="pi pi-arrow-right"
						text
						rounded
						aria-label="Open flow"
						@click="openFlow(data)"
					/>
				</template>
			</Column>
			<template #empty>
				<div class="empty">
					<WandSparkles :size="30" />
					<strong>No visual flows yet</strong>
				</div>
			</template>
		</DataTable>
	</section>

	<AppDialog
		ref="dialogRef"
		v-model:visible="dialog"
		modal
		header="Create a visual flow"
		:style="{ width: '460px', maxWidth: '94vw' }"
		@show="focusDialogControl(dialogRef, '#automation-flow-title')"
	>
		<label for="automation-flow-title">Flow title</label>
		<InputText
			id="automation-flow-title"
			v-model="form.title"
			fluid
			placeholder="Customer support journey"
		/>
		<label for="automation-flow-key">Unique key</label>
		<InputText
			id="automation-flow-key"
			v-model="form.flow_key"
			fluid
			placeholder="company.customer_support"
		/>
		<template #footer>
			<Button label="Cancel" text @click="dialog = false" />
			<Button
				label="Create and open"
				:loading="creating"
				:disabled="!form.title.trim() || !form.flow_key.trim()"
				@click="createFlow"
			/>
		</template>
	</AppDialog>
</template>

<style scoped>
	.flow-list {
		overflow: hidden;
	}
	.list-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 14px 16px;
		border-bottom: 1px solid var(--wa-border);
	}
	.list-toolbar > span {
		color: var(--wa-muted);
		font-size: 12px;
		white-space: nowrap;
	}
	.search-box {
		width: min(360px, 100%);
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 8px 11px;
		border: 1px solid var(--wa-border);
		border-radius: 9px;
		color: var(--wa-muted);
		background: var(--wa-surface-muted);
	}
	.search-box input {
		width: 100%;
		border: 0;
		outline: 0;
		color: var(--wa-text);
		background: transparent;
		font: inherit;
	}
	.flow-name {
		display: flex;
		align-items: center;
		gap: 11px;
		border: 0;
		color: var(--wa-text);
		background: transparent;
		text-align: left;
		cursor: pointer;
	}
	.flow-name > span {
		width: 36px;
		height: 36px;
		display: grid;
		place-items: center;
		border-radius: 10px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}
	.flow-name strong,
	.flow-name small {
		display: block;
	}
	.flow-name small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.loading {
		display: grid;
		gap: 8px;
		padding: 15px;
	}
	.empty {
		min-height: 280px;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: var(--wa-muted);
	}
	.empty strong {
		color: var(--wa-text);
	}
	label {
		display: block;
		margin: 15px 0 7px;
		font-size: 12px;
		font-weight: 700;
	}
	@media (max-width: 640px) {
		.list-toolbar {
			align-items: stretch;
			flex-direction: column;
		}
		.search-box {
			width: 100%;
		}
		.open-flow-action {
			display: none;
		}
	}
</style>
