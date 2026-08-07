<script setup>
	import { onBeforeUnmount, onMounted, ref } from 'vue'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import { Building2, Link2, MessageSquareText, RefreshCw, UsersRound } from 'lucide-vue-next'

	import AsyncState from '@/components/AsyncState.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import ContactSourcesCard from '@/features/settings/components/ContactSourcesCard.vue'
	import TransportSettingsCard from '@/features/settings/components/TransportSettingsCard.vue'
	import { useSessionStore } from '@/stores/session'

	const session = useSessionStore()
	let unsubscribeContactSources = null
	let contactSourceRefresh = null
	let loadSequence = 0
	const loading = ref(true)
	const loadError = ref('')
	const workspace = ref({
		channels: [],
		workspaces: [],
		solutions: [],
		contact_sources: [],
		inventory: {},
	})

	async function load() {
		const request = ++loadSequence
		loading.value = true
		loadError.value = ''
		try {
			const result = await call('frappe_whatsapp_core.frontend_api.settings_workspace')
			if (request !== loadSequence) return
			workspace.value = result
		} catch (error) {
			if (request === loadSequence)
				loadError.value = errorMessage(error, 'Unable to load Core settings.')
		} finally {
			if (request === loadSequence) loading.value = false
		}
	}

	onMounted(() => {
		load()
		const site = session.boot?.site
		unsubscribeContactSources = subscribe(site, 'whatsapp_core_contact_sources', () => {
			window.clearTimeout(contactSourceRefresh)
			contactSourceRefresh = window.setTimeout(load, 200)
		})
	})

	onBeforeUnmount(() => {
		window.clearTimeout(contactSourceRefresh)
		unsubscribeContactSources?.()
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Company configuration</div>
			<h1>Core Settings</h1>
			<p>
				{{ workspace.site || 'Current Frappe site' }} · {{ workspace.time_zone || 'UTC' }}
			</p>
		</div>
		<Button label="Refresh inventory" outlined @click="load">
			<template #icon><RefreshCw :size="16" /></template>
		</Button>
	</div>
	<AsyncState v-if="loadError" :error="loadError" @retry="load" />
	<template v-else>
		<section class="summary-grid">
			<article class="surface-card">
				<UsersRound :size="19" />
				<div>
					<small>Identities</small
					><strong>{{ workspace.inventory.identities || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card">
				<Link2 :size="19" />
				<div>
					<small>Verified bindings</small
					><strong>{{ workspace.inventory.verified_bindings || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card">
				<Building2 :size="19" />
				<div>
					<small>Conversations</small
					><strong>{{ workspace.inventory.conversations || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card">
				<MessageSquareText :size="19" />
				<div>
					<small>Messages</small><strong>{{ workspace.inventory.messages || 0 }}</strong>
				</div>
			</article>
		</section>

		<div class="boundary-note">
			<Building2 :size="18" />
			<div>
				<strong>Install Core, connect the Hub, start working</strong>
				<span
					>Core owns the site experience. The separate Integration Hub owns Meta
					onboarding, template administration and durable delivery.</span
				>
			</div>
		</div>

		<TransportSettingsCard
			:workspace="workspace"
			:can-manage="Boolean(session.boot?.can_manage)"
			@saved="workspace = $event"
		/>

		<ContactSourcesCard
			:sources="workspace.contact_sources || []"
			:can-manage="Boolean(session.boot?.can_manage)"
			@saved="load"
		/>

		<div class="settings-grid">
			<section class="surface-card settings-card">
				<header>
					<div>
						<div class="eyebrow">Assigned by Integration</div>
						<h2>Channels</h2>
					</div>
					<Tag
						:value="`${workspace.channels.length} channels`"
						severity="info"
						rounded
					/>
				</header>
				<div v-if="loading" class="loading"><Skeleton height="120px" /></div>
				<DataTable v-else :value="workspace.channels" striped-rows>
					<Column field="display_name" header="Channel" />
					<Column field="provider" header="Provider" />
					<Column field="phone_number_id" header="Phone number ID" />
					<Column header="Site">
						<template #body="{ data }">
							<Tag
								:value="data.enabled ? 'Enabled' : 'Disabled'"
								:severity="data.enabled ? 'success' : 'secondary'"
								rounded
							/>
						</template>
					</Column>
				</DataTable>
			</section>

			<section class="surface-card settings-card">
				<header>
					<div>
						<div class="eyebrow">Tenant isolation</div>
						<h2>Workspaces</h2>
					</div>
					<Tag
						:value="`${workspace.workspaces.length} workspaces`"
						severity="success"
						rounded
					/>
				</header>
				<div v-if="loading" class="loading"><Skeleton height="120px" /></div>
				<DataTable v-else :value="workspace.workspaces" striped-rows>
					<Column field="display_name" header="Workspace" />
					<Column field="workspace_key" header="Key" />
					<Column field="solution" header="Solution">
						<template #body="{ data }">{{ data.solution || '—' }}</template>
					</Column>
					<Column header="Status">
						<template #body="{ data }">
							<Tag
								:value="data.enabled ? 'Enabled' : 'Disabled'"
								:severity="data.enabled ? 'success' : 'secondary'"
								rounded
							/>
						</template>
					</Column>
				</DataTable>
			</section>
		</div>

		<section class="surface-card settings-card">
			<header>
				<div>
					<div class="eyebrow">Installed company packs</div>
					<h2>Solutions</h2>
				</div>
			</header>
			<DataTable :value="workspace.solutions" striped-rows>
				<Column field="display_name" header="Solution" />
				<Column field="solution_key" header="Key" />
				<Column field="version" header="Version" />
				<Column field="status" header="Status">
					<template #body="{ data }">
						<Tag
							:value="data.status"
							:severity="data.status === 'Active' ? 'success' : 'secondary'"
							rounded
						/>
					</template>
				</Column>
			</DataTable>
		</section>
	</template>
</template>

<style scoped>
	.summary-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
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

	.boundary-note {
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

	.boundary-note strong,
	.boundary-note span {
		display: block;
	}

	.boundary-note span {
		margin-top: 3px;
		color: #56736a;
		font-size: 9px;
	}

	.settings-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 16px;
	}

	.settings-card {
		overflow: hidden;
		margin-bottom: 16px;
	}

	.settings-card header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 17px 18px;
		border-bottom: 1px solid var(--wa-border);
	}

	h2 {
		margin: 3px 0 0;
		font-size: 15px;
	}

	@media (max-width: 980px) {
		.summary-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.settings-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
