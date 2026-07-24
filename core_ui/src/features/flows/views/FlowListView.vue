<script setup>
	import { onMounted, ref } from 'vue'
	import { useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import DataTable from 'primevue/datatable'
	import Column from 'primevue/column'
	import Tag from 'primevue/tag'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Skeleton from 'primevue/skeleton'
	import { GitBranch, Plus, Search, WandSparkles } from 'lucide-vue-next'
	import { call } from '@/services/frappe'

	const router = useRouter()
	const loading = ref(true)
	const creating = ref(false)
	const dialog = ref(false)
	const flows = ref([])
	const filter = ref('')
	const form = ref({ title: '', flow_key: '' })

	async function load() {
		loading.value = true
		try {
			flows.value = await call('frappe_whatsapp_core.frontend_api.list_flows')
		} finally {
			loading.value = false
		}
	}

	async function createFlow() {
		creating.value = true
		try {
			const name = await call(
				'frappe_whatsapp_core.frontend_api.create_starter_flow',
				form.value,
			)
			dialog.value = false
			router.push({ name: 'flow-builder', params: { flowName: name } })
		} finally {
			creating.value = false
		}
	}

	function severity(status) {
		return status === 'Published' ? 'success' : status === 'Retired' ? 'danger' : 'warn'
	}

	onMounted(load)
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Automation</div>
			<h1>Flow Builder</h1>
			<p>Create reusable WhatsApp journeys without writing business logic into the relay.</p>
		</div>
		<Button label="Create flow" @click="dialog = true"
			><template #icon><Plus :size="16" /></template
		></Button>
	</div>

	<section class="surface-card flow-list">
		<div class="list-toolbar">
			<div class="search-box">
				<Search :size="16" /><input v-model="filter" placeholder="Search flows..." />
			</div>
			<span>{{ flows.length }} flows</span>
		</div>
		<div v-if="loading" class="loading">
			<Skeleton v-for="i in 5" :key="i" height="56px" />
		</div>
		<DataTable v-else :value="flows" striped-rows>
			<Column header="Flow">
				<template #body="{ data }">
					<button
						class="flow-name"
						@click="
							router.push({ name: 'flow-builder', params: { flowName: data.name } })
						"
					>
						<span><GitBranch :size="17" /></span>
						<div>
							<strong>{{ data.title }}</strong
							><small>{{ data.flow_key }}</small>
						</div>
					</button>
				</template>
			</Column>
			<Column field="status" header="Status"
				><template #body="{ data }"
					><Tag
						:value="data.status"
						:severity="severity(data.status)"
						rounded /></template
			></Column>
			<Column field="active_version" header="Active version"
				><template #body="{ data }">{{ data.active_version || '—' }}</template></Column
			>
			<Column field="modified" header="Last updated" />
			<Column
				><template #body="{ data }"
					><Button
						icon="pi pi-arrow-right"
						text
						rounded
						@click="
							router.push({ name: 'flow-builder', params: { flowName: data.name } })
						" /></template
			></Column>
			<template #empty
				><div class="empty">
					<WandSparkles :size="30" /><strong>No flows yet</strong
					><span>Create your first visual automation.</span>
				</div></template
			>
		</DataTable>
	</section>

	<Dialog
		v-model:visible="dialog"
		modal
		header="Create a starter flow"
		:style="{ width: '430px' }"
	>
		<div class="dialog-copy">
			<WandSparkles :size="20" />
			<p>Start with a working Yes/No branch. You can replace every node on the canvas.</p>
		</div>
		<label>Flow title</label
		><InputText v-model="form.title" fluid placeholder="Customer review" />
		<label>Unique key</label
		><InputText v-model="form.flow_key" fluid placeholder="company.customer_review" />
		<template #footer
			><Button label="Cancel" text @click="dialog = false" /><Button
				label="Create and open"
				:loading="creating"
				@click="createFlow"
		/></template>
	</Dialog>
</template>

<style scoped>
	.flow-list {
		overflow: hidden;
	}
	.list-toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 15px 17px;
		border-bottom: 1px solid var(--wa-border);
	}
	.list-toolbar > span {
		color: #7e8b84;
		font-size: 10px;
	}
	.search-box {
		width: 310px;
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
</style>
