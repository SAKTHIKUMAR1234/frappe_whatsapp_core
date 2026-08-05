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
	import Textarea from 'primevue/textarea'
	import { Cloud, GitBranch, Plus, Search, WandSparkles } from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'
	import {
		createFlow,
		flowWorkspace,
		getBusinessPublicKey,
		migrateFlows,
		setBusinessPublicKey,
	} from '@/features/flows/services/flowService'
	import { errorMessage } from '@/services/frappe'
	import { useSessionStore } from '@/stores/session'

	const router = useRouter()
	const toast = useToast()
	const session = useSessionStore()
	const loading = ref(true)
	const creating = ref(false)
	const dialog = ref(false)
	const operating = ref(false)
	const migrateDialog = ref(false)
	const keyDialog = ref(false)
	const workspace = ref({ accounts: [], flows: [], selected_account: '' })
	const selectedAccount = ref('')
	const filter = ref('')
	const form = reactive({ flow_name: '', categories: ['OTHER'], endpoint_uri: '' })
	const migration = reactive({ source_waba_id: '', source_flow_names: '' })
	const businessPublicKey = ref('')
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

	async function openKeyDialog() {
		operating.value = true
		try {
			const result = await getBusinessPublicKey(selectedAccount.value)
			businessPublicKey.value =
				result.data?.business_public_key || result.business_public_key || ''
			keyDialog.value = true
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Flow key unavailable',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			operating.value = false
		}
	}

	async function saveBusinessPublicKey() {
		operating.value = true
		try {
			await setBusinessPublicKey(selectedAccount.value, businessPublicKey.value.trim())
			keyDialog.value = false
			toast.add({ severity: 'success', summary: 'Flow encryption key saved', life: 3500 })
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Flow key not saved',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			operating.value = false
		}
	}

	async function migrateNativeFlows() {
		operating.value = true
		try {
			const names = migration.source_flow_names
				.split(/[\n,]+/)
				.map((value) => value.trim())
				.filter(Boolean)
			await migrateFlows(selectedAccount.value, migration.source_waba_id.trim(), names)
			migrateDialog.value = false
			toast.add({ severity: 'success', summary: 'Flow migration requested', life: 3500 })
			await load()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Flows not migrated',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			operating.value = false
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
		<div v-if="canManage" class="heading-actions">
			<Button
				label="Encryption key"
				severity="secondary"
				outlined
				:loading="operating"
				:disabled="!selectedAccount"
				@click="openKeyDialog"
			/>
			<Button
				label="Migrate Flows"
				severity="secondary"
				outlined
				:disabled="!selectedAccount"
				@click="migrateDialog = true"
			/>
			<Button label="Create Meta Flow" :disabled="!selectedAccount" @click="dialog = true">
				<template #icon><Plus :size="16" /></template>
			</Button>
		</div>
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
	<Dialog
		v-model:visible="migrateDialog"
		modal
		header="Migrate Meta Flows"
		:style="{ width: '470px', maxWidth: '94vw' }"
	>
		<p class="dialog-help">
			Copy selected Flows from another WABA into the currently selected destination account.
		</p>
		<label>Source WABA ID</label><InputText v-model="migration.source_waba_id" fluid />
		<label>Source Flow names <small>optional; comma or line separated</small></label
		><Textarea v-model="migration.source_flow_names" rows="6" fluid />
		<template #footer
			><Button label="Cancel" text @click="migrateDialog = false" /><Button
				label="Migrate"
				:loading="operating"
				:disabled="!migration.source_waba_id.trim()"
				@click="migrateNativeFlows"
		/></template>
	</Dialog>
	<Dialog
		v-model:visible="keyDialog"
		modal
		header="Flow encryption public key"
		:style="{ width: '620px', maxWidth: '94vw' }"
	>
		<p class="dialog-help">
			Meta uses this public key for encrypted Flow endpoint data. The private key must remain
			in your endpoint service.
		</p>
		<Textarea
			v-model="businessPublicKey"
			rows="12"
			fluid
			class="key-editor"
			placeholder="-----BEGIN PUBLIC KEY-----"
		/>
		<template #footer
			><Button label="Cancel" text @click="keyDialog = false" /><Button
				label="Save key"
				:loading="operating"
				:disabled="!businessPublicKey.trim()"
				@click="saveBusinessPublicKey"
		/></template>
	</Dialog>
</template>

<style scoped>
	.flow-list {
		overflow: hidden;
	}
	.heading-actions {
		display: flex;
		gap: 8px;
		flex-wrap: wrap;
	}
	.dialog-help {
		margin: 0 0 16px;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.55;
	}
	.key-editor {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
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
