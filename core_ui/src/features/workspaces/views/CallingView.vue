<script setup>
	import { onMounted, ref } from 'vue'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import { call, errorMessage } from '@/services/frappe'

	const loading = ref(false),
		error = ref(''),
		account = ref('')
	const workspace = ref({ accounts: [], calls: [], settings: {}, selected_account: '' })
	async function load(selected = account.value) {
		loading.value = true
		error.value = ''
		try {
			workspace.value = await call('frappe_whatsapp_core.calling.calling_workspace', {
				account_name: selected,
			})
			account.value = workspace.value.selected_account
		} catch (e) {
			error.value = errorMessage(e)
		} finally {
			loading.value = false
		}
	}
	onMounted(() => load(''))
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">WhatsApp Business Calling API</div>
			<h1>Calling</h1>
			<p>
				Meta signaling, permissions and call lifecycle logs. Audio media runs through
				configured WebRTC or SIP infrastructure.
			</p>
		</div>
	</div>
	<div v-if="error" class="error-banner">{{ error }}</div>
	<section class="surface-card panel">
		<div class="toolbar">
			<Select
				v-model="account"
				:options="workspace.accounts"
				option-label="display_name"
				option-value="account_name"
				@change="load($event.value)"
			/><Tag
				:value="workspace.settings?.calling?.status || 'Not configured'"
				severity="info"
			/>
		</div>
		<DataTable
			:value="workspace.calls || []"
			:loading="loading"
			striped-rows
			responsive-layout="scroll"
			><Column field="call_id" header="Call ID" /><Column
				field="direction"
				header="Direction"
			/><Column field="remote_number" header="Remote party" /><Column
				field="status"
				header="Status"
			/><Column field="started_at" header="Started" /><Column
				field="ended_at"
				header="Ended"
			/><template #empty
				><div class="empty">No call events received yet.</div></template
			></DataTable
		>
	</section>
</template>
<style scoped>
	.panel {
		padding: 16px;
	}
	.toolbar {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 14px;
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
	@media (max-width: 600px) {
		.toolbar {
			align-items: stretch;
			flex-direction: column;
		}
	}
</style>
