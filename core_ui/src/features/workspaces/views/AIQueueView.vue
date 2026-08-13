<script setup>
	import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
	import { useToast } from 'primevue/usetoast'
	import Button from 'primevue/button'
	import Checkbox from 'primevue/checkbox'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import AppDialog from '@/components/AppDialog.vue'
	import InputText from 'primevue/inputtext'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import Textarea from 'primevue/textarea'
	import { Bot, CircleCheck, Layers3, RefreshCw, TriangleAlert } from 'lucide-vue-next'

	import AsyncState from '@/components/AsyncState.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'
	import { formatDateTime } from '@/utils/datetime'
	import { focusDialogControl } from '@/utils/focus'

	const toast = useToast()
	const session = useSessionStore()
	const unsubscribers = []
	let realtimeRefresh = null
	let loadSequence = 0
	const loading = ref(true)
	const saving = ref(false)
	const loadError = ref('')
	const dialogVisible = ref(false)
	const dialogRef = ref(null)
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
		const request = ++loadSequence
		if (!silent) loading.value = true
		loadError.value = ''
		const selectedNames = preserveSelection
			? new Set(selected.value.map((row) => row.name))
			: new Set()
		try {
			const loaded = await call('frappe_whatsapp_core.frontend_api.ai_queue_workspace')
			if (request !== loadSequence) return
			workspace.value = loaded
			selected.value = preserveSelection
				? workspace.value.messages.filter((row) => selectedNames.has(row.name))
				: []
		} catch (error) {
			if (request === loadSequence)
				loadError.value = errorMessage(error, 'Unable to load the AI review queue.')
		} finally {
			if (!silent && request === loadSequence) loading.value = false
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

	function toggleMessage(row, checked) {
		selected.value = checked
			? [...selected.value.filter((item) => item.name !== row.name), row]
			: selected.value.filter((item) => item.name !== row.name)
	}

	function isSelected(row) {
		return selected.value.some((item) => item.name === row.name)
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
		</div>
		<div class="heading-actions">
			<Button label="Refresh" outlined :loading="loading" :disabled="loading" @click="load">
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
				class="desktop-table"
				v-model:selection="selected"
				:value="workspace.messages"
				data-key="name"
				striped-rows
			>
				<Column selection-mode="multiple" header-style="width: 3rem" />
				<Column field="conversation_label" header="Conversation">
					<template #body="{ data }">
						<strong class="conversation-label">{{ data.conversation_label }}</strong>
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
				<Column field="provider_timestamp" header="Received">
					<template #body="{ data }">{{
						formatDateTime(data.provider_timestamp)
					}}</template>
				</Column>
				<template #empty>
					<div class="empty">
						<CircleCheck :size="30" />
						<strong>Queue is clear</strong>
						<span>Every materialized message belongs to a topic.</span>
					</div>
				</template>
			</DataTable>
			<div v-if="!loading" class="mobile-queue">
				<label
					v-for="message in workspace.messages"
					:key="message.name"
					class="message-card"
				>
					<Checkbox
						:model-value="isSelected(message)"
						binary
						@update:model-value="toggleMessage(message, $event)"
					/>
					<span>
						<strong>{{ message.conversation_label }}</strong>
						<p>{{ message.body || `(${message.message_type})` }}</p>
						<small>
							<Tag :value="message.direction" severity="secondary" rounded />
							<time :datetime="message.provider_timestamp || undefined">{{
								formatDateTime(message.provider_timestamp)
							}}</time>
						</small>
					</span>
				</label>
				<div v-if="!workspace.messages.length" class="empty">
					<CircleCheck :size="30" />
					<strong>Queue is clear</strong>
					<span>Every materialized message belongs to a topic.</span>
				</div>
			</div>
		</section>

		<section class="surface-card invocation-card">
			<header>
				<div>
					<div class="eyebrow">Audited automation</div>
					<h2>Recent MCP activity</h2>
				</div>
			</header>
			<DataTable class="desktop-table" :value="workspace.invocations" striped-rows>
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
				<Column field="creation" header="Time">
					<template #body="{ data }">{{ formatDateTime(data.creation) }}</template>
				</Column>
			</DataTable>
			<div class="mobile-invocations">
				<article v-for="invocation in workspace.invocations" :key="invocation.name">
					<div>
						<strong>{{ invocation.tool_name }}</strong>
						<small
							>{{ invocation.user }} ·
							{{ formatDateTime(invocation.creation) }}</small
						>
					</div>
					<span>
						<Tag
							:value="invocation.status"
							:severity="invocationSeverity(invocation.status)"
							rounded
						/>
						<small>{{ invocation.duration_ms }} ms</small>
					</span>
				</article>
				<div v-if="!workspace.invocations.length" class="empty compact">
					<span>No recent MCP activity.</span>
				</div>
			</div>
		</section>

		<AppDialog
			ref="dialogRef"
			v-model:visible="dialogVisible"
			modal
			header="Create conversation topic"
			:style="{ width: '470px' }"
			@show="focusDialogControl(dialogRef, '#topic-title')"
		>
			<div class="dialog-copy">
				<strong>{{ selected.length }} messages</strong>
				<span
					>Grouping is auditable and exclusive; a message cannot silently belong to two
					topics.</span
				>
			</div>
			<label for="topic-title">Topic title</label>
			<InputText
				id="topic-title"
				v-model="form.title"
				fluid
				placeholder="Credit note request"
			/>
			<label for="topic-category">Category</label>
			<InputText id="topic-category" v-model="form.category" fluid placeholder="Complaint" />
			<label for="topic-summary">Summary</label>
			<Textarea
				id="topic-summary"
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
		</AppDialog>
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
		color: var(--wa-success);
	}

	.summary-grid article.attention {
		color: var(--wa-warning);
	}

	.summary-grid article.danger {
		color: var(--wa-danger);
	}

	.summary-grid small,
	.summary-grid strong {
		display: block;
	}

	.summary-grid small {
		color: var(--wa-muted);
		font-size: 12px;
	}

	.summary-grid strong {
		margin-top: 4px;
		color: var(--wa-text);
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
		font-size: 12px;
	}

	.conversation-label {
		color: var(--wa-text);
		font-size: 12px;
	}

	.mobile-queue,
	.mobile-invocations {
		display: none;
	}

	.message-preview {
		max-width: 440px;
		margin: 0;
		overflow: hidden;
		font-size: 12px;
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
		font-size: 12px;
		line-height: 1.45;
	}

	label {
		display: block;
		margin: 13px 0 6px;
		font-size: 12px;
		font-weight: 700;
	}

	@media (max-width: 980px) {
		.summary-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}

	@media (max-width: 700px) {
		.desktop-table {
			display: none;
		}

		.mobile-queue,
		.mobile-invocations {
			display: grid;
		}

		.message-card {
			display: grid;
			grid-template-columns: auto minmax(0, 1fr);
			gap: 12px;
			align-items: start;
			padding: 14px 16px;
			border-bottom: 1px solid var(--wa-border-soft);
			cursor: pointer;
		}

		.message-card > span,
		.message-card small,
		.mobile-invocations article > div,
		.mobile-invocations article > span {
			min-width: 0;
			display: flex;
		}

		.message-card > span,
		.mobile-invocations article > div,
		.mobile-invocations article > span {
			flex-direction: column;
			gap: 5px;
		}

		.message-card p {
			margin: 0;
			overflow: hidden;
			color: var(--wa-muted);
			font-size: 12px;
			line-height: 1.45;
			display: -webkit-box;
			-webkit-box-orient: vertical;
			-webkit-line-clamp: 3;
		}

		.message-card small {
			align-items: center;
			justify-content: space-between;
			gap: 8px;
			color: var(--wa-muted);
			font-size: 11px;
		}

		.message-card time {
			overflow: hidden;
			white-space: nowrap;
			text-overflow: ellipsis;
		}

		.mobile-invocations article {
			display: flex;
			justify-content: space-between;
			gap: 12px;
			padding: 14px 16px;
			border-bottom: 1px solid var(--wa-border-soft);
		}

		.mobile-invocations article > div small,
		.mobile-invocations article > span small {
			color: var(--wa-muted);
			font-size: 11px;
		}

		.mobile-invocations article > span {
			align-items: flex-end;
			flex: none;
		}

		.empty.compact {
			min-height: 100px;
		}
	}
</style>
