<script setup>
	import { computed, onMounted, ref } from 'vue'
	import { useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import { GitBranch, MessageCircleQuestion } from 'lucide-vue-next'
	import AsyncState from '@/components/AsyncState.vue'
	import FlowResponseCard from '@/features/flows/components/FlowResponseCard.vue'
	import { flowWorkspace } from '@/features/flows/services/flowService'
	import { call, errorMessage } from '@/services/frappe'

	const router = useRouter()
	const loading = ref(true)
	const loadError = ref('')
	const workspace = ref({ accounts: [], flows: [], selected_account: '' })
	const selectedAccount = ref('')
	const responses = ref([])
	let loadSequence = 0
	const forms = computed(() =>
		workspace.value.flows.filter((flow) =>
			(flow.categories || []).some((category) =>
				['SURVEY', 'LEAD_GENERATION', 'CONTACT_US', 'APPOINTMENT_BOOKING'].includes(
					category,
				),
			),
		),
	)
	async function load(account = selectedAccount.value) {
		const request = ++loadSequence
		loading.value = true
		loadError.value = ''
		try {
			const [loaded, responseRows] = await Promise.all([
				flowWorkspace(account),
				call('frappe_whatsapp_core.flow_responses.list_flow_responses', { limit: 200 }),
			])
			if (request !== loadSequence) return
			workspace.value = loaded
			responses.value = responseRows
			selectedAccount.value = workspace.value.selected_account
		} catch (error) {
			if (request === loadSequence)
				loadError.value = errorMessage(error, 'Unable to load Meta forms and surveys.')
		} finally {
			if (request === loadSequence) loading.value = false
		}
	}
	function open(flow) {
		router.push({
			name: 'flow-builder',
			params: { flowName: flow.id },
			query: { account: selectedAccount.value },
		})
	}
	onMounted(() => load(''))
</script>

<template>
	<div class="page-heading">
		<div>
			<h1>Forms & Surveys</h1>
		</div>
		<Button label="Create Meta Flow" @click="router.push({ name: 'flows' })"
			><template #icon><GitBranch :size="16" /></template
		></Button>
	</div>
	<AsyncState v-if="loadError" :error="loadError" @retry="() => load(selectedAccount)" />
	<template v-else>
		<div class="flow-filter">
			<Select
				v-model="selectedAccount"
				:options="workspace.accounts"
				option-label="display_name"
				option-value="account_name"
				@change="load($event.value)"
			/>
		</div>
		<section class="surface-card poll-table">
			<DataTable :value="forms" :loading="loading" striped-rows
				><Column header="Native Flow"
					><template #body="{ data }"
						><button class="flow-name" @click="open(data)">
							<span><MessageCircleQuestion :size="17" /></span>
							<div>
								<strong>{{ data.name }}</strong
								><small>Meta ID {{ data.id }}</small>
							</div>
						</button></template
					></Column
				><Column header="Category"
					><template #body="{ data }">{{
						(data.categories || []).join(', ')
					}}</template></Column
				><Column field="status" header="Status"
					><template #body="{ data }"
						><Tag
							:value="data.status"
							:severity="data.status === 'PUBLISHED' ? 'success' : 'warn'"
							rounded /></template></Column
				><template #empty
					><div class="empty">
						<MessageCircleQuestion :size="30" /><strong
							>No form-oriented Meta Flows</strong
						><span>Create a SURVEY, LEAD_GENERATION or CONTACT_US Flow.</span>
					</div></template
				></DataTable
			>
		</section>
		<section class="surface-card response-table">
			<header>
				<h2>Flow responses</h2>
				<Tag :value="`${responses.length} records`" rounded />
			</header>
			<DataTable :value="responses" striped-rows scrollable scroll-height="420px">
				<Column field="response_type" header="Type" />
				<Column header="Flow">
					<template #body="{ data }">{{
						data.flow || data.provider_flow_name || '—'
					}}</template>
				</Column>
				<Column field="status" header="Status">
					<template #body="{ data }">
						<Tag
							:value="data.status"
							:severity="data.status === 'Failed' ? 'danger' : 'success'"
							rounded
						/>
					</template>
				</Column>
				<Column field="creation" header="Received" />
				<Column header="Response">
					<template #body="{ data }">
						<FlowResponseCard
							:response="data.response_payload"
							:heading="data.provider_flow_name || data.flow || 'Flow response'"
							:status="data.status"
							compact
						/>
					</template>
				</Column>
				<template #empty><div class="empty">No flow responses yet</div></template>
			</DataTable>
		</section>
	</template>
</template>

<style scoped>
	.flow-filter {
		display: flex;
		justify-content: flex-end;
		margin-bottom: 16px;
	}
	.poll-table {
		overflow: hidden;
	}
	.response-table {
		margin-top: 18px;
		overflow: hidden;
	}
	.response-table > header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 16px;
		border-bottom: 1px solid var(--wa-border);
	}
	.response-table h2 {
		margin: 0;
		font-size: 14px;
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
		color: var(--wa-success);
		background: var(--wa-success-soft);
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
		color: var(--wa-muted);
		font-size: 12px;
	}
	.empty {
		height: 240px;
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
	@media (max-width: 700px) {
		.engine-note {
			align-items: flex-start;
			flex-direction: column;
		}
	}
</style>
