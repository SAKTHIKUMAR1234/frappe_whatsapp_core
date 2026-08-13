<script setup>
	import { onBeforeUnmount, onMounted, ref } from 'vue'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import { BadgeCheck, Ban, MessageSquareText, Pencil, Plus, RefreshCw } from 'lucide-vue-next'

	import AsyncState from '@/components/AsyncState.vue'
	import TemplateEditorDialog from '@/features/templates/components/TemplateEditorDialog.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'

	const session = useSessionStore()
	let realtimeRefresh = null
	let unsubscribeTemplate = null
	let loadSequence = 0
	const loading = ref(true)
	const loadError = ref('')
	const editorVisible = ref(false)
	const selectedTemplate = ref(null)
	const catalog = ref({
		templates: [],
		metrics: {},
	})

	async function load({ silent = false } = {}) {
		const request = ++loadSequence
		if (!silent) loading.value = true
		if (!silent) loadError.value = ''
		try {
			const result = await call('frappe_whatsapp_core.frontend_api.template_catalog')
			if (request !== loadSequence) return
			catalog.value = result
		} catch (error) {
			if (request === loadSequence)
				loadError.value = errorMessage(error, 'Unable to load the template catalog.')
		} finally {
			if (!silent && request === loadSequence) loading.value = false
		}
	}

	function severity(status) {
		if (status === 'APPROVED') return 'success'
		if (status === 'REJECTED') return 'danger'
		if (status === 'IN_REVIEW') return 'info'
		return 'secondary'
	}

	function openEditor(template = null) {
		selectedTemplate.value = template
		editorVisible.value = true
	}

	function canEdit(template) {
		return ['DRAFT', 'APPROVED', 'REJECTED'].includes(template.approval_status)
	}

	function templateSaved() {
		load({ silent: true })
	}

	onMounted(() => {
		load()
		unsubscribeTemplate = subscribe(session.boot?.site, 'whatsapp_core_template', () => {
			window.clearTimeout(realtimeRefresh)
			realtimeRefresh = window.setTimeout(() => load({ silent: true }), 200)
		})
	})

	onBeforeUnmount(() => {
		window.clearTimeout(realtimeRefresh)
		unsubscribeTemplate?.()
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<h1>Available Templates</h1>
		</div>
		<div class="heading-actions">
			<Button label="Refresh view" outlined @click="load">
				<template #icon><RefreshCw :size="16" /></template>
			</Button>
			<Button label="Create template" @click="openEditor()">
				<template #icon><Plus :size="16" /></template>
			</Button>
		</div>
	</div>
	<AsyncState v-if="loadError" :error="loadError" @retry="load" />
	<template v-else>
		<section class="summary-grid">
			<article class="surface-card">
				<BadgeCheck :size="19" />
				<div>
					<small>Approved</small><strong>{{ catalog.metrics.approved || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card">
				<MessageSquareText :size="19" />
				<div>
					<small>Available here</small
					><strong>{{ catalog.metrics.available || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card">
				<Ban :size="19" />
				<div>
					<small>Disabled</small><strong>{{ catalog.metrics.disabled || 0 }}</strong>
				</div>
			</article>
		</section>

		<section class="surface-card catalog-table">
			<div v-if="loading" class="loading">
				<Skeleton v-for="index in 5" :key="index" height="58px" />
			</div>
			<DataTable v-else :value="catalog.templates" striped-rows>
				<Column header="Template">
					<template #body="{ data }">
						<div class="template-name">
							<span><MessageSquareText :size="17" /></span>
							<div>
								<strong>{{ data.template_name }}</strong
								><small>{{ data.name }}</small>
							</div>
						</div>
					</template>
				</Column>
				<Column field="language_code" header="Language" />
				<Column field="category" header="Category">
					<template #body="{ data }">{{ data.category || '—' }}</template>
				</Column>
				<Column header="Preview">
					<template #body="{ data }">
						<p class="preview">{{ data.body_text || 'No text preview' }}</p>
					</template>
				</Column>
				<Column header="Meta status">
					<template #body="{ data }">
						<Tag
							:value="data.approval_status"
							:severity="severity(data.approval_status)"
							rounded
						/>
					</template>
				</Column>
				<Column header="Availability">
					<template #body="{ data }">
						<Tag
							:value="data.enabled ? 'Enabled' : 'Disabled'"
							:severity="data.enabled ? 'success' : 'secondary'"
							rounded
						/>
					</template>
				</Column>
				<Column header="Actions">
					<template #body="{ data }">
						<Button v-if="canEdit(data)" label="Edit" text @click="openEditor(data)">
							<template #icon><Pencil :size="15" /></template>
						</Button>
						<span v-else class="pending-copy">Await Meta review</span>
					</template>
				</Column>
				<template #empty>
					<div class="empty">
						<MessageSquareText :size="30" />
						<strong>No template assignments received</strong>
						<span>Assign a Meta template to this workspace in Integration Desk.</span>
					</div>
				</template>
			</DataTable>
		</section>
	</template>
	<TemplateEditorDialog
		v-model="editorVisible"
		:template="selectedTemplate"
		@saved="templateSaved"
	/>
</template>

<style scoped>
	.ownership-note {
		display: flex;
		align-items: center;
		gap: 11px;
		padding: 12px 15px;
		margin-bottom: 15px;
		border: 1px solid color-mix(in srgb, var(--wa-success) 24%, var(--wa-border));
		border-radius: 13px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}

	.ownership-note strong,
	.ownership-note span {
		display: block;
	}

	.ownership-note strong {
		font-size: 11px;
	}

	.ownership-note span {
		margin-top: 2px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.summary-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 16px;
	}

	.heading-actions {
		display: flex;
		align-items: center;
		gap: 9px;
	}

	.pending-copy {
		color: var(--wa-muted);
		font-size: 12px;
	}

	.summary-grid article {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 17px;
		color: var(--wa-success);
	}

	.summary-grid small,
	.summary-grid strong {
		display: block;
	}

	.summary-grid small {
		margin-bottom: 4px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.summary-grid strong {
		color: var(--wa-text);
		font-size: 20px;
	}

	.catalog-table {
		overflow: hidden;
	}

	.template-name {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.template-name > span {
		display: grid;
		place-items: center;
		width: 35px;
		height: 35px;
		border-radius: 10px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}

	.template-name strong,
	.template-name small {
		display: block;
	}

	.template-name strong {
		font-size: 11px;
	}

	.template-name small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.preview {
		max-width: 320px;
		margin: 0;
		overflow: hidden;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.45;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.loading {
		display: grid;
		gap: 8px;
		padding: 15px;
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

	@media (max-width: 850px) {
		.summary-grid {
			grid-template-columns: 1fr;
		}

		.heading-actions {
			width: 100%;
		}

		.heading-actions :deep(.p-button) {
			min-height: 44px;
			flex: 1;
		}
	}
</style>
