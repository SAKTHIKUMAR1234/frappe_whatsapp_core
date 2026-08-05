<script setup>
	import { computed, onMounted, reactive, ref } from 'vue'
	import { useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import MultiSelect from 'primevue/multiselect'
	import Select from 'primevue/select'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import { Cloud, GitBranch, Plus, Search, WandSparkles } from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'
	import { createFlow, flowWorkspace } from '@/features/flows/services/flowService'
	import { errorMessage } from '@/services/frappe'
	import { useSessionStore } from '@/stores/session'

	const router = useRouter()
	const toast = useToast()
	const session = useSessionStore()
	const loading = ref(true)
	const creating = ref(false)
	const dialog = ref(false)
	const workspace = ref({ accounts: [], flows: [], selected_account: '' })
	const selectedAccount = ref('')
	const filter = ref('')
	const form = reactive({ flow_name: '', categories: ['OTHER'], endpoint_uri: '' })
	const categories = [
		'SIGN_UP',
		'SIGN_IN',
		'APPOINTMENT_BOOKING',
		'LEAD_GENERATION',
		'CONTACT_US',
		'CUSTOMER_SUPPORT',
		'SURVEY',
		'OTHER',
	]
	const canManage = computed(() => Boolean(session.boot?.can_manage))
	const filteredFlows = computed(() => {
		const query = filter.value.trim().toLowerCase()
		if (!query) return workspace.value.flows
		return workspace.value.flows.filter((flow) =>
			[flow.name, flow.id, flow.status, ...(flow.categories || [])]
				.join(' ')
				.toLowerCase()
				.includes(query),
		)
	})

	async function load(account = selectedAccount.value) {
		loading.value = true
		try {
			workspace.value = await flowWorkspace(account)
			selectedAccount.value = workspace.value.selected_account
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Meta Flows unavailable',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			loading.value = false
		}
	}

	async function createNativeFlow() {
		creating.value = true
		try {
			const result = await createFlow({
				account_name: selectedAccount.value,
				flow_name: form.flow_name,
				categories: form.categories,
				endpoint_uri: form.endpoint_uri || null,
			})
			const flowId = result.data?.id
			if (!flowId) throw new Error('Meta did not return a Flow ID')
			dialog.value = false
			router.push({
				name: 'flow-builder',
				params: { flowName: flowId },
				query: { account: selectedAccount.value },
			})
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
		router.push({
			name: 'flow-builder',
			params: { flowName: flow.id },
			query: { account: selectedAccount.value },
		})
	}

	function severity(status) {
		return status === 'PUBLISHED' ? 'success' : status === 'DEPRECATED' ? 'danger' : 'warn'
	}

	onMounted(() => load(''))
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Meta-hosted experiences</div>
			<h1>WhatsApp Flows</h1>
			<p>
				Create and publish native Meta Flows. Frappe stores audit logs, not a second Flow
				runtime.
			</p>
		</div>
		<Button
			v-if="canManage"
			label="Create Meta Flow"
			:disabled="!selectedAccount"
			@click="dialog = true"
		>
			<template #icon><Plus :size="16" /></template>
		</Button>
	</div>

	<section class="surface-card flow-list">
		<div class="list-toolbar">
			<div class="search-box">
				<Search :size="16" /><input v-model="filter" placeholder="Search Meta Flows…" />
			</div>
			<Select
				v-model="selectedAccount"
				:options="workspace.accounts"
				option-label="display_name"
				option-value="account_name"
				placeholder="WhatsApp account"
				@change="load($event.value)"
			/>
			<span>{{ filteredFlows.length }} flows</span>
		</div>
		<div v-if="loading" class="loading">
			<Skeleton v-for="i in 5" :key="i" height="56px" />
		</div>
		<DataTable v-else :value="filteredFlows" striped-rows>
			<Column header="Flow">
				<template #body="{ data }">
					<button class="flow-name" @click="openFlow(data)">
						<span><GitBranch :size="17" /></span>
						<div>
							<strong>{{ data.name }}</strong
							><small>Meta ID {{ data.id }}</small>
						</div>
					</button>
				</template>
			</Column>
			<Column header="Categories"
				><template #body="{ data }"
					><span class="categories">{{
						(data.categories || []).join(', ') || '—'
					}}</span></template
				></Column
			>
			<Column field="status" header="Status"
				><template #body="{ data }"
					><Tag
						:value="data.status"
						:severity="severity(data.status)"
						rounded /></template
			></Column>
			<Column header="Health"
				><template #body="{ data }">{{
					data.health_status?.can_send_message === 'BLOCKED' ? 'Blocked' : 'Ready'
				}}</template></Column
			>
			<Column
				><template #body="{ data }"
					><Button
						icon="pi pi-arrow-right"
						text
						rounded
						@click="openFlow(data)" /></template
			></Column>
			<template #empty
				><div class="empty">
					<Cloud :size="30" /><strong>No Meta Flows found</strong
					><span>Create one for this WhatsApp account.</span>
				</div></template
			>
		</DataTable>
	</section>

	<Dialog
		v-model:visible="dialog"
		modal
		header="Create native Meta Flow"
		:style="{ width: '470px', maxWidth: '94vw' }"
	>
		<div class="dialog-copy">
			<WandSparkles :size="20" />
			<p>
				The Flow is created directly in Meta. You can upload and validate flow.json on the
				next screen.
			</p>
		</div>
		<label>Flow name</label
		><InputText v-model="form.flow_name" fluid placeholder="Customer support intake" />
		<label>Categories</label
		><MultiSelect v-model="form.categories" :options="categories" fluid display="chip" />
		<label>Data endpoint URL <small>optional</small></label
		><InputText v-model="form.endpoint_uri" fluid placeholder="https://…" />
		<template #footer
			><Button label="Cancel" text @click="dialog = false" /><Button
				label="Create in Meta"
				:loading="creating"
				:disabled="!form.flow_name.trim() || !form.categories.length"
				@click="createNativeFlow"
		/></template>
	</Dialog>
</template>

<style scoped>
	.flow-list {
		overflow: hidden;
	}
	.list-toolbar {
		display: grid;
		grid-template-columns: minmax(220px, 1fr) 260px auto;
		align-items: center;
		gap: 12px;
		padding: 15px 17px;
		border-bottom: 1px solid var(--wa-border);
	}
	.list-toolbar > span,
	.categories {
		color: #718078;
		font-size: 10px;
	}
	.search-box {
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 8px 11px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		color: #829088;
		background: #f8faf9;
	}
	.search-box input {
		width: 100%;
		border: 0;
		outline: 0;
		background: transparent;
		font-size: 11px;
	}
	.flow-name {
		display: flex;
		align-items: center;
		gap: 11px;
		border: 0;
		background: transparent;
		text-align: left;
		cursor: pointer;
	}
	.flow-name > span {
		display: grid;
		place-items: center;
		width: 35px;
		height: 35px;
		border-radius: 10px;
		color: #087255;
		background: #dff7ed;
	}
	.flow-name strong,
	.flow-name small {
		display: block;
	}
	.flow-name strong {
		font-size: 12px;
	}
	.flow-name small {
		margin-top: 3px;
		color: #87938d;
		font-size: 9px;
	}
	.loading {
		display: grid;
		gap: 8px;
		padding: 15px;
	}
	.empty {
		height: 260px;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: #819088;
	}
	.empty strong {
		color: #24312c;
	}
	.dialog-copy {
		display: flex;
		gap: 10px;
		padding: 12px;
		margin-bottom: 17px;
		border-radius: 10px;
		color: #126249;
		background: #e9f8f2;
	}
	.dialog-copy p {
		margin: 0;
		font-size: 11px;
		line-height: 1.5;
	}
	label {
		display: block;
		margin: 15px 0 7px;
		font-size: 11px;
		font-weight: 700;
	}
	label small {
		color: #8a9690;
		font-weight: 500;
	}
	@media (max-width: 700px) {
		.list-toolbar {
			grid-template-columns: 1fr;
		}
	}
</style>
