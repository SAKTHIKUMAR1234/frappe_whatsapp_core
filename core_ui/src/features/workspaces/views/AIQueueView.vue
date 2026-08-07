<script setup>
	import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
	import { useToast } from 'primevue/usetoast'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import Textarea from 'primevue/textarea'
	import { Bot, CircleCheck, Layers3, RefreshCw, TriangleAlert } from 'lucide-vue-next'

	import AsyncState from '@/components/AsyncState.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'

	const toast = useToast()
	const session = useSessionStore()
	const unsubscribers = []
	let realtimeRefresh = null
	const loading = ref(true)
	const saving = ref(false)
	const loadError = ref('')
	const dialogVisible = ref(false)
	const selected = ref([])
	const workspace = ref({
		messages: [],
		invocations: [],
		metrics: {},
	})
	const form = ref({
		title: '',
		category: '',
		summary: '',
	})

	const selectedConversations = computed(
		() => new Set(selected.value.map((row) => row.conversation)),
	)
	const canClassify = computed(
		() => selected.value.length > 0 && selectedConversations.value.size === 1,
	)

	async function load({ silent = false, preserveSelection = false } = {}) {
		if (!silent) loading.value = true
		loadError.value = ''
		const selectedNames = preserveSelection
			? new Set(selected.value.map((row) => row.name))
			: new Set()
		try {
			workspace.value = await call('frappe_whatsapp_core.frontend_api.ai_queue_workspace')
			selected.value = preserveSelection
				? workspace.value.messages.filter((row) => selectedNames.has(row.name))
				: []
		} catch (error) {
			loadError.value = errorMessage(error, 'Unable to load the AI review queue.')
		} finally {
			if (!silent) loading.value = false
		}
	}

	function queueRealtimeRefresh() {
		window.clearTimeout(realtimeRefresh)
		realtimeRefresh = window.setTimeout(
			() => load({ silent: true, preserveSelection: true }),
			200,
		)
	}

	function openClassification() {
		if (!canClassify.value) return
		form.value = { title: '', category: '', summary: '' }
		dialogVisible.value = true
	}

	async function classify() {
		saving.value = true
		try {
			await call('frappe_whatsapp_core.frontend_api.classify_messages', {
				conversation: selected.value[0].conversation,
				message_names: selected.value.map((row) => row.name),
				...form.value,
			})
			dialogVisible.value = false
			await load()
			toast.add({
				severity: 'success',
				summary: 'Topic created',
				detail: 'The selected messages are no longer in the unclassified queue.',
				life: 3500,
			})
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Could not create topic',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			saving.value = false
		}
	}

	function invocationSeverity(status) {
		return status === 'Completed' ? 'success' : 'danger'
	}

	onMounted(() => {
		load()
		const site = session.boot?.site
		for (const event of [
			'whatsapp_core_message',
			'whatsapp_core_topic',
			'whatsapp_core_mcp_invocation',
		]) {
			unsubscribers.push(subscribe(site, event, queueRealtimeRefresh))
		}
	})

	onBeforeUnmount(() => {
		window.clearTimeout(realtimeRefresh)
		unsubscribers.splice(0).forEach((unsubscribe) => unsubscribe())
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Human review</div>
			<h1>AI Queue</h1>
			<p>
				Classify uncertain messages manually or let an authenticated MCP client handle
				them.
			</p>
		</div>
		<div class="heading-actions">
			<Button label="Refresh" outlined @click="load">
				<template #icon><RefreshCw :size="16" /></template>
			</Button>
			<Button label="Create topic" :disabled="!canClassify" @click="openClassification">
				<template #icon><Layers3 :size="16" /></template>
			</Button>
		</div>
	</div>
	<AsyncState v-if="loadError" :error="loadError" @retry="load" />
	<template v-else>
		<section class="summary-grid">
			<article class="surface-card attention">
				<TriangleAlert :size="19" />
				<div>
					<small>Needs review</small
					><strong>{{ workspace.metrics.needs_review || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card">
				<CircleCheck :size="19" />
				<div>
					<small>MCP completed</small
					><strong>{{ workspace.metrics.mcp_completed || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card">
				<Layers3 :size="19" />
				<div>
					<small>Open topics</small
					><strong>{{ workspace.metrics.open_topics || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card danger">
				<Bot :size="19" />
				<div>
					<small>MCP failures</small
					><strong>{{ workspace.metrics.mcp_failed || 0 }}</strong>
				</div>
			</article>
		</section>

		<section class="surface-card queue-card">
			<header>
				<div>
					<div class="eyebrow">Permanent queue</div>
					<h2>Unclassified messages</h2>
				</div>
				<small v-if="selectedConversations.size > 1"
					>Select messages from one conversation at a time.</small
				>
				<small v-else>{{ selected.length }} selected</small>
			</header>
			<div v-if="loading" class="loading">
				<Skeleton v-for="index in 5" :key="index" height="58px" />
			</div>
			<DataTable
				v-else
				v-model:selection="selected"
				:value="workspace.messages"
				data-key="name"
				striped-rows
			>
				<Column selection-mode="multiple" header-style="width: 3rem" />
				<Column field="conversation" header="Conversation">
					<template #body="{ data }">
						<code>{{ data.conversation }}</code>
					</template>
				</Column>
				<Column field="body" header="Message">
					<template #body="{ data }">
						<p class="message-preview">{{ data.body || `(${data.message_type})` }}</p>
					</template>
				</Column>
				<Column field="direction" header="Direction">
					<template #body="{ data }">
						<Tag :value="data.direction" severity="secondary" rounded />
					</template>
				</Column>
				<Column field="provider_timestamp" header="Received" />
				<template #empty>
					<div class="empty">
						<CircleCheck :size="30" />
						<strong>Queue is clear</strong>
						<span>Every materialized message belongs to a topic.</span>
					</div>
				</template>
			</DataTable>
		</section>

		<section class="surface-card invocation-card">
			<header>
				<div>
					<div class="eyebrow">Audited automation</div>
					<h2>Recent MCP activity</h2>
				</div>
			</header>
			<DataTable :value="workspace.invocations" striped-rows>
				<Column field="tool_name" header="Tool" />
				<Column field="user" header="User" />
				<Column field="duration_ms" header="Duration">
					<template #body="{ data }">{{ data.duration_ms }} ms</template>
				</Column>
				<Column field="status" header="Status">
					<template #body="{ data }">
						<Tag
							:value="data.status"
							:severity="invocationSeverity(data.status)"
							rounded
						/>
					</template>
				</Column>
				<Column field="creation" header="Time" />
			</DataTable>
		</section>

		<Dialog
			v-model:visible="dialogVisible"
			modal
			header="Create conversation topic"
			:style="{ width: '470px' }"
		>
			<div class="dialog-copy">
				<strong>{{ selected.length }} messages</strong>
				<span
					>Grouping is auditable and exclusive; a message cannot silently belong to two
					topics.</span
				>
			</div>
			<label>Topic title</label>
			<InputText v-model="form.title" fluid placeholder="Credit note request" />
			<label>Category</label>
			<InputText v-model="form.category" fluid placeholder="Complaint" />
			<label>Summary</label>
			<Textarea
				v-model="form.summary"
				rows="4"
				fluid
				placeholder="Short operator-approved summary"
			/>
			<template #footer>
				<Button label="Cancel" text @click="dialogVisible = false" />
				<Button
					label="Create topic"
					:disabled="!form.title.trim()"
					:loading="saving"
					@click="classify"
				/>
			</template>
		</Dialog>
	</template>
</template>

<style scoped>
	.heading-actions,
	.queue-card header,
	.invocation-card header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}

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

	.summary-grid article.attention {
		color: #bf6a16;
	}

	.summary-grid article.danger {
		color: #b43c42;
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

	.queue-card,
	.invocation-card {
		overflow: hidden;
		margin-bottom: 16px;
	}

	.queue-card header,
	.invocation-card header {
		padding: 17px 18px;
		border-bottom: 1px solid var(--wa-border);
	}

	h2 {
		margin: 3px 0 0;
		font-size: 15px;
	}

	header small {
		color: var(--wa-muted);
		font-size: 9px;
	}

	code {
		color: #476059;
		font-size: 9px;
	}

	.message-preview {
		max-width: 440px;
		margin: 0;
		overflow: hidden;
		font-size: 10px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dialog-copy {
		padding: 12px;
		margin-bottom: 14px;
		border-radius: 12px;
		background: var(--wa-mint);
	}

	.dialog-copy strong,
	.dialog-copy span {
		display: block;
	}

	.dialog-copy span {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 10px;
		line-height: 1.45;
	}

	label {
		display: block;
		margin: 13px 0 6px;
		font-size: 10px;
		font-weight: 700;
	}

	@media (max-width: 980px) {
		.summary-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
</style>
