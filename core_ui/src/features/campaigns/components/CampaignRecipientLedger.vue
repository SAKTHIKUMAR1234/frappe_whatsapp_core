<script setup>
	import { computed, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import AppDialog from '@/components/AppDialog.vue'
	import InputText from 'primevue/inputtext'
	import Message from 'primevue/message'
	import Select from 'primevue/select'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import { RotateCw, Search } from 'lucide-vue-next'

	import { call, errorMessage } from '@/services/frappe'
	import { formatDateTime } from '@/utils/datetime'

	const props = defineProps({
		visible: { type: Boolean, default: false },
		campaign: { type: Object, default: null },
	})
	const emit = defineEmits(['update:visible'])

	const rows = ref([])
	const loading = ref(false)
	const loadingMore = ref(false)
	const failure = ref('')
	const search = ref('')
	const status = ref('')
	const total = ref(0)
	const hasMore = ref(false)
	const counts = ref({})
	let searchTimer = null
	let requestSequence = 0

	const statusOptions = computed(() => [
		{
			label: `All (${Object.values(counts.value).reduce((sum, value) => sum + value, 0)})`,
			value: '',
		},
		...['Prepared', 'Queued', 'Sent', 'Delivered', 'Read', 'Failed', 'Skipped'].map(
			(value) => ({ label: `${value} (${counts.value[value] || 0})`, value }),
		),
	])

	function close() {
		emit('update:visible', false)
	}

	async function load({ append = false } = {}) {
		if (!props.campaign?.name) return
		const request = ++requestSequence
		if (append) loadingMore.value = true
		else loading.value = true
		failure.value = ''
		try {
			const result = await call(
				'frappe_whatsapp_core.frontend_api.campaign_recipient_page',
				{
					campaign_name: props.campaign.name,
					search: search.value,
					status: status.value,
					limit: 50,
					offset: append ? rows.value.length : 0,
				},
			)
			if (request !== requestSequence) return
			rows.value = append ? [...rows.value, ...(result.rows || [])] : result.rows || []
			total.value = result.total || 0
			hasMore.value = Boolean(result.has_more)
			counts.value = result.counts || {}
		} catch (error) {
			if (request === requestSequence)
				failure.value = errorMessage(error, 'Unable to load campaign recipients.')
		} finally {
			if (request === requestSequence) {
				loading.value = false
				loadingMore.value = false
			}
		}
	}

	function statusSeverity(value) {
		if (['Delivered', 'Read'].includes(value)) return 'success'
		if (['Queued', 'Sent'].includes(value)) return 'info'
		if (value === 'Failed') return 'danger'
		if (value === 'Prepared') return 'warn'
		return 'secondary'
	}

	function failureText(row) {
		if (row.last_error) return row.last_error
		if (!row.failure) return ''
		if (typeof row.failure === 'object')
			return row.failure.message || row.failure.error || JSON.stringify(row.failure)
		try {
			const parsed = JSON.parse(row.failure)
			return parsed.message || parsed.error || row.failure
		} catch {
			return row.failure
		}
	}

	function responseText(row) {
		return failureText(row) || row.provider_message_id || 'Waiting for relay response'
	}

	watch(
		() => props.visible,
		(visible) => {
			if (!visible) return
			search.value = ''
			status.value = ''
			rows.value = []
			counts.value = {}
			load()
		},
	)

	watch(status, () => {
		if (props.visible) load()
	})

	watch(search, () => {
		window.clearTimeout(searchTimer)
		searchTimer = window.setTimeout(() => {
			if (props.visible) load()
		}, 300)
	})
</script>

<template>
	<AppDialog
		:visible="visible"
		modal
		:header="campaign ? `Recipients · ${campaign.title}` : 'Campaign recipients'"
		:style="{ width: 'min(1080px, 96vw)' }"
		:draggable="false"
		@update:visible="close"
	>
		<div class="ledger-toolbar">
			<div class="search-box">
				<Search :size="16" />
				<InputText
					v-model="search"
					aria-label="Search campaign recipients"
					placeholder="Search contact, phone, response, or error"
				/>
			</div>
			<Select
				v-model="status"
				:options="statusOptions"
				option-label="label"
				option-value="value"
				aria-label="Filter campaign recipients by status"
			/>
			<Button text rounded aria-label="Refresh recipients" :loading="loading" @click="load">
				<RotateCw :size="16" />
			</Button>
		</div>

		<Message v-if="failure" severity="error" :closable="false">{{ failure }}</Message>
		<div v-if="loading" class="ledger-loading">
			<Skeleton v-for="index in 6" :key="index" height="54px" />
		</div>
		<template v-else>
			<div class="ledger-summary">
				{{ total }} matching recipient{{ total === 1 ? '' : 's' }}
			</div>
			<div class="ledger-table-wrap">
				<table class="ledger-table">
					<thead>
						<tr>
							<th>Recipient</th>
							<th>Status</th>
							<th>Response / error</th>
							<th>Attempts</th>
							<th>Updated</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="row in rows" :key="row.name">
							<td>
								<strong>{{ row.display_name }}</strong
								><small>{{ row.secondary_text }}</small>
							</td>
							<td>
								<Tag
									:value="row.status"
									:severity="statusSeverity(row.status)"
									rounded
								/>
							</td>
							<td>
								<span
									class="response"
									:class="{ failed: failureText(row) }"
									:title="responseText(row)"
									>{{ responseText(row) }}</span
								>
							</td>
							<td>{{ row.attempts || 0 }}</td>
							<td>
								{{
									formatDateTime(
										row.completed_at ||
											row.provider_timestamp ||
											row.queued_at,
									)
								}}
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<div class="ledger-cards">
				<article v-for="row in rows" :key="row.name">
					<header>
						<span
							><strong>{{ row.display_name }}</strong
							><small>{{ row.secondary_text }}</small></span
						><Tag :value="row.status" :severity="statusSeverity(row.status)" rounded />
					</header>
					<p :class="{ failed: failureText(row) }">{{ responseText(row) }}</p>
					<footer>
						<span
							>{{ row.attempts || 0 }} attempt{{
								row.attempts === 1 ? '' : 's'
							}}</span
						><time>{{
							formatDateTime(
								row.completed_at || row.provider_timestamp || row.queued_at,
							)
						}}</time>
					</footer>
				</article>
			</div>

			<div v-if="!rows.length" class="ledger-empty">No recipients match this filter.</div>
			<Button
				v-if="hasMore"
				label="Load 50 more"
				outlined
				:loading="loadingMore"
				@click="load({ append: true })"
			/>
		</template>
	</AppDialog>
</template>

<style scoped>
	.ledger-toolbar {
		display: grid;
		grid-template-columns: minmax(240px, 1fr) 190px 44px;
		gap: 10px;
		align-items: center;
		margin-bottom: 14px;
	}
	.search-box {
		display: flex;
		align-items: center;
		gap: 8px;
		padding-left: 11px;
		border: 1px solid var(--wa-border);
		border-radius: 9px;
		color: var(--wa-muted);
	}
	.search-box :deep(input) {
		width: 100%;
		border: 0;
		box-shadow: none;
	}
	.ledger-loading {
		display: grid;
		gap: 7px;
	}
	.ledger-summary {
		margin-bottom: 8px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.ledger-table-wrap {
		max-height: 54vh;
		overflow: auto;
		border: 1px solid var(--wa-border);
		border-radius: 11px;
	}
	.ledger-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	.ledger-table th,
	.ledger-table td {
		padding: 10px 12px;
		border-bottom: 1px solid var(--wa-border);
		text-align: left;
		vertical-align: middle;
	}
	.ledger-table th {
		position: sticky;
		top: 0;
		z-index: 1;
		background: var(--wa-surface);
	}
	.ledger-table td:first-child strong,
	.ledger-table td:first-child small,
	.ledger-cards strong,
	.ledger-cards small {
		display: block;
	}
	.ledger-table td:first-child small,
	.ledger-cards small {
		margin-top: 2px;
		color: var(--wa-muted);
	}
	.response {
		display: block;
		max-width: 320px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--wa-muted);
	}
	.failed {
		color: var(--wa-danger) !important;
	}
	.ledger-empty {
		padding: 44px 16px;
		color: var(--wa-muted);
		text-align: center;
	}
	.ledger-cards {
		display: none;
	}
	@media (max-width: 700px) {
		.ledger-toolbar {
			grid-template-columns: minmax(0, 1fr) 44px;
		}
		.ledger-toolbar > :deep(.p-select) {
			grid-column: 1 / -1;
			grid-row: 2;
		}
		.ledger-table-wrap {
			display: none;
		}
		.ledger-cards {
			display: grid;
			gap: 9px;
			max-height: 55vh;
			overflow: auto;
		}
		.ledger-cards article {
			padding: 12px;
			border: 1px solid var(--wa-border);
			border-radius: 11px;
		}
		.ledger-cards header,
		.ledger-cards footer {
			display: flex;
			align-items: center;
			justify-content: space-between;
			gap: 10px;
		}
		.ledger-cards p {
			margin: 11px 0;
			color: var(--wa-muted);
			font-size: 12px;
			word-break: break-word;
		}
		.ledger-cards footer {
			color: var(--wa-muted);
			font-size: 11px;
		}
	}
</style>
