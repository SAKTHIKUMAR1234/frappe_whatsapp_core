<script setup>
	import { onMounted, ref } from 'vue'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import { call, errorMessage } from '@/services/frappe'

	const loading = ref(false),
		saving = ref(false),
		showCreate = ref(false),
		error = ref('')
	const workspace = ref({ accounts: [], data: [], selected_account: '' })
	const account = ref(''),
		form = ref({ subject: '', description: '', join_approval_mode: 'auto_approve' })
	async function load(selected = account.value) {
		loading.value = true
		error.value = ''
		try {
			workspace.value = await call('frappe_whatsapp_core.groups.group_workspace', {
				account_name: selected,
			})
			account.value = workspace.value.selected_account
		} catch (e) {
			error.value = errorMessage(e)
		} finally {
			loading.value = false
		}
	}
	async function create() {
		saving.value = true
		error.value = ''
		try {
			await call('frappe_whatsapp_core.groups.create_group', {
				account_name: account.value,
				...form.value,
			})
			showCreate.value = false
			form.value = { subject: '', description: '', join_approval_mode: 'auto_approve' }
			await load()
		} catch (e) {
			error.value = errorMessage(e)
		} finally {
			saving.value = false
		}
	}
	onMounted(() => load(''))
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Meta Groups API</div>
			<h1>WhatsApp Groups</h1>
			<p>Create and manage Meta-hosted business groups without leaving Core.</p>
		</div>
		<Button label="Create group" icon="pi pi-plus" @click="showCreate = true" />
	</div>
	<div v-if="error" class="error-banner">{{ error }}</div>
	<section class="surface-card panel">
		<Select
			v-model="account"
			:options="workspace.accounts"
			option-label="display_name"
			option-value="account_name"
			@change="load($event.value)"
		/>
		<DataTable
			:value="workspace.data || []"
			:loading="loading"
			striped-rows
			responsive-layout="scroll"
		>
			<Column field="subject" header="Group" /><Column
				field="description"
				header="Description"
			/><Column field="total_participant_count" header="Participants" /><Column
				field="join_approval_mode"
				header="Join approval"
			/><Column field="id" header="Meta ID" />
			<template #empty
				><div class="empty">No groups returned by this account.</div></template
			>
		</DataTable>
	</section>
	<Dialog
		v-model:visible="showCreate"
		modal
		header="Create WhatsApp group"
		:style="{ width: 'min(34rem, 94vw)' }"
	>
		<div class="form">
			<label>Subject<InputText v-model="form.subject" maxlength="128" /></label
			><label
				>Description<Textarea
					v-model="form.description"
					rows="4"
					maxlength="2048" /></label
			><label
				>Join approval<Select
					v-model="form.join_approval_mode"
					:options="[
						{ label: 'Automatic', value: 'auto_approve' },
						{ label: 'Approval required', value: 'approval_required' },
					]"
					option-label="label"
					option-value="value"
			/></label>
		</div>
		<template #footer
			><Button
				label="Cancel"
				severity="secondary"
				outlined
				@click="showCreate = false" /><Button
				label="Create"
				:loading="saving"
				:disabled="!form.subject.trim()"
				@click="create"
		/></template>
	</Dialog>
</template>
<style scoped>
	.panel {
		padding: 16px;
		display: grid;
		gap: 14px;
	}
	.form {
		display: grid;
		gap: 14px;
	}
	.form label {
		display: grid;
		gap: 6px;
		font-size: 12px;
	}
	.error-banner {
		padding: 10px 14px;
		margin-bottom: 12px;
		border-radius: 10px;
		background: #fff1f1;
		color: #a52222;
	}
	.empty {
		padding: 48px;
		text-align: center;
		color: #7d8983;
	}
</style>
