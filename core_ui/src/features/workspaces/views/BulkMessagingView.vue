<script setup>
	import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import Textarea from 'primevue/textarea'
	import { useConfirm } from 'primevue/useconfirm'
	import { useToast } from 'primevue/usetoast'
	import {
		BadgeCheck,
		CircleDashed,
		Clock3,
		Megaphone,
		Plus,
		Send,
		ShieldCheck,
		Upload,
		Users,
	} from 'lucide-vue-next'

	import AsyncState from '@/components/AsyncState.vue'
	import ContactMultiSelect from '@/features/contacts/components/ContactMultiSelect.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'
	import { focusDialogControl } from '@/utils/focus'

	const toast = useToast()
	const confirm = useConfirm()
	const session = useSessionStore()
	let realtimeRefresh = null
	let unsubscribeCampaign = null
	let unsubscribeTemplate = null
	let loadSequence = 0
	const loading = ref(true)
	const saving = ref(false)
	const loadError = ref('')
	const workspace = ref({
		campaigns: [],
		templates: [],
		channels: [],
		identities: [],
		metrics: {},
	})
	const createDialog = ref(false)
	const prepareDialog = ref(false)
	const authorizationDialog = ref(false)
	const createDialogRef = ref(null)
	const prepareDialogRef = ref(null)
	const authorizationDialogRef = ref(null)
	const selectedCampaign = ref(null)
	const selectedAudience = ref([])
	const importedRecipients = ref({})
	const audienceFile = ref(null)
	const importingAudience = ref(false)
	const importSummary = ref(null)
	const authorizationText = ref('')
	const form = ref({
		title: '',
		campaign_key: '',
		description: '',
		channel: '',
		content_type: 'Template',
		template: '',
		message_text: '',
	})
	const contentTypes = [
		{ label: 'Approved template', value: 'Template' },
		{ label: 'Plain text · open 24-hour windows only', value: 'Text' },
	]

	const approvedTemplates = computed(() =>
		workspace.value.templates.map((template) => ({
			...template,
			label: `${template.template_name} · ${template.language_code}`,
			disabled: template.approval_status !== 'APPROVED',
		})),
	)
	const expectedAuthorization = computed(() =>
		selectedCampaign.value ? `AUTHORIZE ${selectedCampaign.value.campaign_key}` : '',
	)

	watch(
		() => form.value.title,
		(title) => {
			if (!form.value.campaign_key || form.value.campaign_key.startsWith('campaign.')) {
				form.value.campaign_key = `campaign.${title
					.toLowerCase()
					.replace(/[^a-z0-9]+/g, '_')
					.replace(/^_|_$/g, '')}`
			}
		},
	)

	async function load({ silent = false } = {}) {
		const request = ++loadSequence
		if (!silent) loading.value = true
		if (!silent) loadError.value = ''
		try {
			const result = await call('frappe_whatsapp_core.frontend_api.campaign_workspace')
			if (request !== loadSequence) return
			workspace.value = result
		} catch (error) {
			if (request === loadSequence)
				loadError.value = errorMessage(error, 'Unable to load campaigns.')
		} finally {
			if (!silent && request === loadSequence) loading.value = false
		}
	}

	function queueRealtimeRefresh() {
		window.clearTimeout(realtimeRefresh)
		realtimeRefresh = window.setTimeout(() => load({ silent: true }), 200)
	}

	async function createCampaign() {
		saving.value = true
		try {
			await call('frappe_whatsapp_core.frontend_api.create_campaign_draft', form.value)
			createDialog.value = false
			form.value = {
				title: '',
				campaign_key: '',
				description: '',
				channel: '',
				content_type: 'Template',
				template: '',
				message_text: '',
			}
			await load()
			toast.add({
				severity: 'success',
				summary: 'Campaign draft created',
				detail: 'The company layer can now prepare its exact audience.',
				life: 3500,
			})
		} catch (error) {
			showError(error)
		} finally {
			saving.value = false
		}
	}

	function openAuthorization(campaign) {
		selectedCampaign.value = campaign
		authorizationText.value = ''
		authorizationDialog.value = true
	}

	function openPrepare(campaign) {
		selectedCampaign.value = campaign
		selectedAudience.value = []
		importedRecipients.value = {}
		importSummary.value = null
		prepareDialog.value = true
	}

	async function importAudience(event) {
		const file = event.target.files?.[0]
		if (!file) return
		importingAudience.value = true
		try {
			const result = await call(
				'frappe_whatsapp_core.frontend_api.preview_campaign_audience_csv',
				{ csv_text: await file.text() },
			)
			importedRecipients.value = Object.fromEntries(
				result.recipients.map((recipient) => [recipient.identity, recipient]),
			)
			selectedAudience.value = [
				...new Set([
					...selectedAudience.value,
					...result.recipients.map((recipient) => recipient.identity),
				]),
			]
			workspace.value.identities = [
				...workspace.value.identities,
				...result.contacts,
			].filter(
				(contact, index, rows) =>
					rows.findIndex((candidate) => candidate.identity === contact.identity) ===
					index,
			)
			importSummary.value = result
			toast.add({
				severity: result.error_count ? 'warn' : 'success',
				summary: 'Audience CSV checked',
				detail: `${result.resolved_count} contacts resolved${result.error_count ? ` · ${result.error_count} rows need attention` : ''}.`,
				life: 4500,
			})
		} catch (error) {
			showError(error)
		} finally {
			importingAudience.value = false
			event.target.value = ''
		}
	}

	async function prepare() {
		saving.value = true
		try {
			const recipients = selectedAudience.value.map(
				(identity) => importedRecipients.value[identity] || { identity },
			)
			await call('frappe_whatsapp_core.frontend_api.prepare_campaign_audience', {
				campaign_name: selectedCampaign.value.name,
				recipients,
			})
			prepareDialog.value = false
			await load()
			toast.add({
				severity: 'success',
				summary: 'Exact audience prepared',
				detail: `${selectedAudience.value.length} active identities passed validation.`,
				life: 3500,
			})
		} catch (error) {
			showError(error)
		} finally {
			saving.value = false
		}
	}

	async function authorize() {
		saving.value = true
		try {
			await call('frappe_whatsapp_core.frontend_api.authorize_campaign_send', {
				campaign_name: selectedCampaign.value.name,
				confirmation: authorizationText.value,
			})
			authorizationDialog.value = false
			await load()
			toast.add({
				severity: 'success',
				summary: 'SEND authorized',
				detail: 'Authorization is recorded separately from Meta approval.',
				life: 3500,
			})
		} catch (error) {
			showError(error)
		} finally {
			saving.value = false
		}
	}

	async function launch(campaign) {
		saving.value = true
		try {
			await call('frappe_whatsapp_core.frontend_api.launch_campaign_send', {
				campaign_name: campaign.name,
			})
			await load()
			toast.add({
				severity: 'success',
				summary: 'Campaign started',
				detail: 'Recipients are being queued through durable 40-message relay batches.',
				life: 4000,
			})
		} catch (error) {
			showError(error)
		} finally {
			saving.value = false
		}
	}

	function cancel(campaign) {
		confirm.require({
			header: 'Cancel campaign?',
			message:
				'Prepared recipients will be skipped and queued messages that have not reached the relay will be made terminal. Messages already accepted by Meta cannot be recalled.',
			icon: 'pi pi-exclamation-triangle',
			rejectLabel: 'Keep running',
			acceptLabel: 'Cancel campaign',
			acceptClass: 'p-button-danger',
			accept: async () => {
				saving.value = true
				try {
					await call('frappe_whatsapp_core.frontend_api.cancel_campaign_send', {
						campaign_name: campaign.name,
					})
					await load()
					toast.add({
						severity: 'success',
						summary: 'Campaign cancelled',
						detail: 'No remaining recipient will be submitted.',
						life: 3500,
					})
				} catch (error) {
					showError(error)
				} finally {
					saving.value = false
				}
			},
		})
	}

	function statusSeverity(status) {
		if (status === 'Completed') return 'success'
		if (['Running', 'Scheduled'].includes(status)) return 'info'
		if (status === 'Cancelled') return 'danger'
		if (status === 'Prepared') return 'warn'
		return 'secondary'
	}

	function showError(error) {
		toast.add({
			severity: 'error',
			summary: 'Campaign action blocked',
			detail: errorMessage(error, 'Campaign action failed.'),
			life: 5000,
		})
	}

	onMounted(() => {
		load()
		const site = session.boot?.site
		unsubscribeCampaign = subscribe(site, 'whatsapp_core_campaign', queueRealtimeRefresh)
		unsubscribeTemplate = subscribe(site, 'whatsapp_core_template', queueRealtimeRefresh)
	})

	onBeforeUnmount(() => {
		window.clearTimeout(realtimeRefresh)
		unsubscribeCampaign?.()
		unsubscribeTemplate?.()
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Engage safely</div>
			<h1>Bulk Messaging</h1>
			<p>Prepare an exact audience, approve the template, then authorize SEND separately.</p>
		</div>
		<Button label="New campaign" @click="createDialog = true">
			<template #icon><Plus :size="16" /></template>
		</Button>
	</div>
	<AsyncState v-if="loadError" :error="loadError" @retry="load" />
	<template v-else>
		<section class="metric-grid">
			<article class="surface-card metric-card">
				<span class="metric-icon draft"><CircleDashed :size="18" /></span>
				<div>
					<small>Draft / prepared</small
					><strong>{{ workspace.metrics.drafts || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card metric-card">
				<span class="metric-icon scheduled"><Clock3 :size="18" /></span>
				<div>
					<small>Scheduled</small><strong>{{ workspace.metrics.scheduled || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card metric-card">
				<span class="metric-icon delivered"><BadgeCheck :size="18" /></span>
				<div>
					<small>Delivered / read</small
					><strong>{{ workspace.metrics.delivered || 0 }}</strong>
				</div>
			</article>
		</section>

		<section class="surface-card safety-pipeline">
			<div>
				<Users :size="18" /><span
					><strong>1. Audience</strong><small>Exact Core identities</small></span
				>
			</div>
			<i></i>
			<div>
				<BadgeCheck :size="18" /><span
					><strong>2. Meta approval</strong><small>Owned by Integration</small></span
				>
			</div>
			<i></i>
			<div>
				<ShieldCheck :size="18" /><span
					><strong>3. SEND gate</strong><small>Named human approval</small></span
				>
			</div>
			<i></i>
			<div>
				<Send :size="18" /><span
					><strong>4. Durable queue</strong
					><small>Parallel relay workers with rate limits</small></span
				>
			</div>
		</section>

		<section class="surface-card campaign-list">
			<div class="list-heading">
				<div>
					<div class="eyebrow">Campaign records</div>
					<h2>Campaigns</h2>
				</div>
				<span>{{ workspace.campaigns.length }} total</span>
			</div>

			<div v-if="loading" class="loading">
				<Skeleton v-for="index in 5" :key="index" height="58px" />
			</div>
			<DataTable v-else :value="workspace.campaigns" striped-rows>
				<Column header="Campaign">
					<template #body="{ data }">
						<div class="campaign-name">
							<span><Megaphone :size="17" /></span>
							<div>
								<strong>{{ data.title }}</strong
								><small>{{ data.campaign_key }}</small>
							</div>
						</div>
					</template>
				</Column>
				<Column header="Audience">
					<template #body="{ data }">
						<div class="count-cell">
							<strong>{{ data.recipient_count }}</strong
							><small>recipients</small>
						</div>
					</template>
				</Column>
				<Column header="Safety gates">
					<template #body="{ data }">
						<div class="gate-stack">
							<span
								:class="{
									passed:
										data.content_type === 'Text' ||
										data.template_approval_status === 'APPROVED',
								}"
							>
								<i></i
								>{{
									data.content_type === 'Text'
										? '24-hour window required'
										: `Meta ${data.template_approval_status.toLowerCase()}`
								}}
							</span>
							<span :class="{ passed: data.send_authorized }">
								<i></i
								>{{
									data.send_authorized
										? `SEND · ${data.authorized_by}`
										: 'SEND locked'
								}}
							</span>
						</div>
					</template>
				</Column>
				<Column header="Progress">
					<template #body="{ data }">
						<div class="progress-copy">
							<span>{{ data.queued_count }} queued</span>
							<span>{{ data.delivered_count + data.read_count }} delivered</span>
							<span v-if="data.failed_count" class="failure"
								>{{ data.failed_count }} failed</span
							>
						</div>
					</template>
				</Column>
				<Column field="status" header="Status">
					<template #body="{ data }">
						<Tag
							:value="data.status"
							:severity="statusSeverity(data.status)"
							rounded
						/>
					</template>
				</Column>
				<Column>
					<template #body="{ data }">
						<div v-if="['Running', 'Scheduled', 'Paused'].includes(data.status)">
							<Button
								label="Cancel campaign"
								severity="danger"
								size="small"
								outlined
								:loading="saving"
								@click="cancel(data)"
							/>
						</div>
						<Button
							v-if="
								['Draft', 'Prepared'].includes(data.status) &&
								!data.send_authorized &&
								!data.recipient_count
							"
							label="Prepare audience"
							size="small"
							outlined
							@click="openPrepare(data)"
						/>
						<Button
							v-else-if="data.status === 'Prepared' && !data.send_authorized"
							label="Authorize"
							size="small"
							outlined
							@click="openAuthorization(data)"
						/>
						<Button
							v-else-if="data.status === 'Prepared' && data.send_authorized"
							label="Start"
							size="small"
							:loading="saving"
							@click="launch(data)"
						/>
					</template>
				</Column>
				<template #empty>
					<div class="empty">
						<Megaphone :size="30" />
						<strong>No campaigns yet</strong>
						<span
							>Create a draft; the business layer supplies its exact audience.</span
						>
					</div>
				</template>
			</DataTable>
		</section>

		<Dialog
			ref="createDialogRef"
			v-model:visible="createDialog"
			modal
			header="Create campaign draft"
			:style="{ width: '470px' }"
			@show="focusDialogControl(createDialogRef, '#campaign-title')"
		>
			<div class="dialog-note">
				This creates only a draft. Template campaigns require Meta approval. Plain text is
				accepted only for contacts whose 24-hour service window is still open. Both require
				an exact audience and separate SEND authorization.
			</div>
			<label for="campaign-title">Campaign title</label>
			<InputText
				id="campaign-title"
				v-model="form.title"
				fluid
				placeholder="August retailer follow-up"
			/>
			<label for="campaign-key">Unique key</label>
			<InputText
				id="campaign-key"
				v-model="form.campaign_key"
				fluid
				placeholder="campaign.august_follow_up"
			/>
			<label id="campaign-channel-label">Channel</label>
			<Select
				v-model="form.channel"
				aria-labelledby="campaign-channel-label"
				:options="workspace.channels"
				option-label="display_name"
				option-value="name"
				placeholder="Select assigned number"
				fluid
			/>
			<label id="campaign-content-type-label">Message type</label>
			<Select
				v-model="form.content_type"
				aria-labelledby="campaign-content-type-label"
				:options="contentTypes"
				option-label="label"
				option-value="value"
				fluid
			/>
			<label v-if="form.content_type === 'Template'" id="campaign-template-label"
				>Template</label
			>
			<Select
				v-if="form.content_type === 'Template'"
				v-model="form.template"
				aria-labelledby="campaign-template-label"
				:options="approvedTemplates"
				option-label="label"
				option-value="name"
				option-disabled="disabled"
				placeholder="Select an approved template"
				fluid
			/>
			<label v-else for="campaign-message-text">Message</label>
			<Textarea
				v-if="form.content_type === 'Text'"
				id="campaign-message-text"
				v-model="form.message_text"
				rows="4"
				maxlength="4096"
				fluid
				placeholder="Plain text for contacts with an open 24-hour service window"
			/>
			<label for="campaign-description">Description</label>
			<Textarea
				id="campaign-description"
				v-model="form.description"
				rows="3"
				fluid
				placeholder="Purpose and audience notes"
			/>
			<template #footer>
				<Button label="Cancel" text @click="createDialog = false" />
				<Button
					label="Create draft"
					:disabled="
						!form.title ||
						!form.campaign_key ||
						!form.channel ||
						(form.content_type === 'Template'
							? !form.template
							: !form.message_text.trim())
					"
					:loading="saving"
					@click="createCampaign"
				/>
			</template>
		</Dialog>

		<Dialog
			ref="prepareDialogRef"
			v-model:visible="prepareDialog"
			modal
			header="Prepare exact audience"
			@show="focusDialogControl(prepareDialogRef)"
			:style="{ width: '620px', maxWidth: '94vw' }"
		>
			<div class="dialog-note">
				Select the exact active Core identities for this campaign. Preparing replaces the
				current unauthorized audience and does not send anything.
			</div>
			<label id="campaign-recipients-label">Recipients</label>
			<ContactMultiSelect
				v-model="selectedAudience"
				aria-labelledby="campaign-recipients-label"
				:options="workspace.identities"
				placeholder="Search active Core contacts"
			/>
			<div class="audience-import-row">
				<small class="selection-count">{{ selectedAudience.length }} selected</small>
				<input
					ref="audienceFile"
					type="file"
					accept=".csv,text/csv"
					hidden
					@change="importAudience"
				/>
				<Button
					label="Import CSV"
					severity="secondary"
					outlined
					:loading="importingAudience"
					@click="audienceFile?.click()"
				>
					<template #icon><Upload :size="15" /></template>
				</Button>
			</div>
			<small class="csv-format">
				CSV: identity or phone; optional message/text for plain-text personalization,
				body_1, body_2, header_1, button_0, or components_json for templates.
			</small>
			<div v-if="importSummary?.error_count" class="import-errors">
				<strong>{{ importSummary.error_count }} rows were not imported</strong>
				<span v-for="row in importSummary.errors.slice(0, 5)" :key="row.row">
					Row {{ row.row }}: {{ row.error }}
				</span>
			</div>
			<template #footer>
				<Button label="Cancel" text @click="prepareDialog = false" />
				<Button
					label="Prepare audience"
					:disabled="!selectedAudience.length"
					:loading="saving"
					@click="prepare"
				/>
			</template>
		</Dialog>

		<Dialog
			ref="authorizationDialogRef"
			v-model:visible="authorizationDialog"
			modal
			header="Authorize SEND"
			@show="focusDialogControl(authorizationDialogRef)"
			:style="{ width: '470px' }"
		>
			<div class="authorization-warning">
				<ShieldCheck :size="22" />
				<div>
					<strong>This is independent of Meta template approval.</strong>
					<p>
						{{ selectedCampaign?.recipient_count || 0 }} prepared recipients will
						become eligible to queue.
					</p>
				</div>
			</div>
			<label for="campaign-authorization"
				>Type exactly: <code>{{ expectedAuthorization }}</code></label
			>
			<InputText id="campaign-authorization" v-model="authorizationText" fluid />
			<template #footer>
				<Button label="Cancel" text @click="authorizationDialog = false" />
				<Button
					label="Authorize SEND"
					severity="danger"
					:disabled="authorizationText !== expectedAuthorization"
					:loading="saving"
					@click="authorize"
				/>
			</template>
		</Dialog>
	</template>
</template>

<style scoped>
	.metric-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 16px;
	}
	.identity-option strong,
	.identity-option small {
		display: block;
	}
	.identity-option strong {
		font-size: 11px;
	}
	.identity-option small,
	.selection-count {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.audience-import-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.csv-format {
		display: block;
		margin-top: 8px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.import-errors {
		display: grid;
		gap: 4px;
		margin-top: 10px;
		padding: 10px 12px;
		border-radius: 10px;
		background: var(--wa-warning-soft);
		color: var(--wa-warning-text, var(--wa-text));
		font-size: 11px;
	}

	.metric-card {
		display: flex;
		align-items: center;
		gap: 13px;
		padding: 17px;
	}

	.metric-icon {
		display: grid;
		place-items: center;
		width: 39px;
		height: 39px;
		border-radius: 12px;
	}

	.metric-icon.draft {
		color: var(--wa-warning);
		background: var(--wa-warning-soft);
	}

	.metric-icon.scheduled {
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
	}

	.metric-icon.delivered {
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}

	.metric-card small,
	.metric-card strong {
		display: block;
	}

	.metric-card small {
		margin-bottom: 4px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.metric-card strong {
		font-size: 21px;
	}

	.safety-pipeline {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 14px 17px;
		margin-bottom: 16px;
	}

	.safety-pipeline > div {
		display: flex;
		align-items: center;
		gap: 9px;
		min-width: 0;
		color: var(--wa-success);
	}

	.safety-pipeline > div span,
	.safety-pipeline strong,
	.safety-pipeline small {
		display: block;
	}

	.safety-pipeline strong {
		color: var(--wa-text);
		font-size: 12px;
	}

	.safety-pipeline small {
		margin-top: 2px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.safety-pipeline > i {
		flex: 1;
		height: 1px;
		background: #dce7e2;
	}

	.campaign-list {
		overflow: hidden;
	}

	.list-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 16px 18px;
		border-bottom: 1px solid var(--wa-border);
	}

	.list-heading h2 {
		margin: 4px 0 0;
		font-size: 16px;
	}

	.list-heading > span {
		color: var(--wa-muted);
		font-size: 12px;
	}

	.campaign-name {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.campaign-name > span {
		display: grid;
		place-items: center;
		width: 35px;
		height: 35px;
		border-radius: 10px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}

	.campaign-name strong,
	.campaign-name small,
	.count-cell strong,
	.count-cell small {
		display: block;
	}

	.campaign-name strong {
		font-size: 11px;
	}

	.campaign-name small,
	.count-cell small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.count-cell strong {
		font-size: 13px;
	}

	.gate-stack {
		display: grid;
		gap: 5px;
	}

	.gate-stack span {
		color: var(--wa-warning);
		font-size: 12px;
		white-space: nowrap;
	}

	.gate-stack i {
		display: inline-block;
		width: 6px;
		height: 6px;
		margin-right: 5px;
		border-radius: 50%;
		background: #e7a72d;
	}

	.gate-stack span.passed {
		color: var(--wa-success);
	}

	.gate-stack span.passed i {
		background: #23a477;
	}

	.progress-copy {
		display: grid;
		gap: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.progress-copy .failure {
		color: var(--wa-danger);
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

	.dialog-note,
	.authorization-warning {
		padding: 12px;
		border-radius: 11px;
		font-size: 11px;
		line-height: 1.5;
	}

	.dialog-note {
		color: var(--wa-muted);
		background: var(--wa-surface-muted);
	}

	.authorization-warning {
		display: flex;
		gap: 10px;
		color: var(--wa-warning);
		background: var(--wa-warning-soft);
	}

	.authorization-warning p {
		margin: 3px 0 0;
	}

	label {
		display: block;
		margin: 14px 0 7px;
		font-size: 12px;
		font-weight: 700;
	}

	label code {
		color: var(--wa-danger);
	}

	@media (max-width: 950px) {
		.metric-grid {
			grid-template-columns: 1fr;
		}

		.safety-pipeline {
			align-items: flex-start;
			flex-direction: column;
		}

		.safety-pipeline > i {
			width: 1px;
			height: 12px;
			margin-left: 8px;
		}
	}
</style>
