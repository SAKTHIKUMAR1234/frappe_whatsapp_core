<script setup>
	import { computed, onMounted, ref } from 'vue'
	import { useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import { GitBranch, MessageCircleQuestion } from 'lucide-vue-next'
	import { flowWorkspace } from '@/features/flows/services/flowService'

	const router = useRouter()
	const loading = ref(true)
	const workspace = ref({ accounts: [], flows: [], selected_account: '' })
	const selectedAccount = ref('')
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
		loading.value = true
		try {
			workspace.value = await flowWorkspace(account)
			selectedAccount.value = workspace.value.selected_account
		} finally {
			loading.value = false
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
			<div class="eyebrow">Meta-hosted structured collection</div>
			<h1>Forms & Surveys</h1>
			<p>
				Survey and lead forms are native WhatsApp Flows—rendered, validated and hosted by
				Meta.
			</p>
		</div>
		<Button label="Create Meta Flow" @click="router.push({ name: 'flows' })"
			><template #icon><GitBranch :size="16" /></template
		></Button>
	</div>
	<div class="engine-note">
		<MessageCircleQuestion :size="18" />
		<div>
			<strong>No message-by-message form emulation</strong
			><span
				>Core launches the published Meta Flow and stores only WhatsApp events and
				operational logs.</span
			>
		</div>
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
					<MessageCircleQuestion :size="30" /><strong>No form-oriented Meta Flows</strong
					><span>Create a SURVEY, LEAD_GENERATION or CONTACT_US Flow.</span>
				</div></template
			></DataTable
		>
	</section>
</template>

<style scoped>
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
	.engine-note > div {
		flex: 1;
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
	.empty {
		height: 240px;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: #829088;
	}
	.empty strong {
		color: #28362f;
	}
	@media (max-width: 700px) {
		.engine-note {
			align-items: flex-start;
			flex-direction: column;
		}
	}
</style>
