<script setup>
	import { computed, onMounted, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import Textarea from 'primevue/textarea'
	import { useToast } from 'primevue/usetoast'
	import {
		BadgeCheck,
		CircleDashed,
		Clock3,
		Megaphone,
		Plus,
		Send,
		ShieldCheck,
		Users,
	} from 'lucide-vue-next'

	import { call } from '@/services/frappe'

	const toast = useToast()
	const loading = ref(true)
	const saving = ref(false)
	const workspace = ref({
		campaigns: [],
		templates: [],
		channels: [],
		metrics: {},
	})
	const createDialog = ref(false)
	const authorizationDialog = ref(false)
	const selectedCampaign = ref(null)
	const authorizationText = ref('')
	const form = ref({
		title: '',
		campaign_key: '',
		description: '',
		channel: '',
		template: '',
	})

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

	async function load() {
		loading.value = true
		try {
			workspace.value = await call('frappe_whatsapp_core.frontend_api.campaign_workspace')
		} finally {
			loading.value = false
		}
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
				template: '',
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
				detail: 'Recipients are being queued one at a time through the durable relay.',
				life: 4000,
			})
		} catch (error) {
			showError(error)
		} finally {
			saving.value = false
		}
	}

	function statusSeverity(status) {
		if (status === 'Completed') return 'success'
		if (['Running', 'Scheduled'].includes(status)) return 'info'
		if (status === 'Cancelled') return 'danger'
		if (status === 'Prepared') return 'warn'
		return 'secondary'
	}

	function showError(error) {
		const payload = error?.response?.data
		const detail = payload?.exception
			? payload.exception.split(':').at(-1)
			: payload?.message || error.message || 'Request failed'
		toast.add({
			severity: 'error',
			summary: 'Campaign action blocked',
			detail,
			life: 5000,
		})
	}

	onMounted(load)
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

	<section class="metric-grid">
		<article class="surface-card metric-card">
			<span class="metric-icon draft"><CircleDashed :size="18" /></span>
			<div>
				<small>Draft / prepared</small><strong>{{ workspace.metrics.drafts || 0 }}</strong>
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
				><strong>4. Durable queue</strong><small>One Meta send at a time</small></span
			>
		</div>
	</section>

	<section class="surface-card campaign-list">
		<div class="list-heading">
			<div>
				<div class="eyebrow">Site-local records</div>
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
						<span :class="{ passed: data.template_approval_status === 'APPROVED' }">
							<i></i>Meta {{ data.template_approval_status.toLowerCase() }}
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
					<Tag :value="data.status" :severity="statusSeverity(data.status)" rounded />
				</template>
			</Column>
			<Column>
				<template #body="{ data }">
					<Button
						v-if="data.status === 'Prepared' && !data.send_authorized"
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
					<span>Create a draft; the business layer supplies its exact audience.</span>
				</div>
			</template>
		</DataTable>
	</section>

	<Dialog
		v-model:visible="createDialog"
		modal
		header="Create campaign draft"
		:style="{ width: '470px' }"
	>
		<div class="dialog-note">
			This creates only a draft. It cannot send until an exact audience, Meta-approved
			template and separate SEND authorization are present.
		</div>
		<label>Campaign title</label>
		<InputText v-model="form.title" fluid placeholder="August retailer follow-up" />
		<label>Unique key</label>
		<InputText v-model="form.campaign_key" fluid placeholder="campaign.august_follow_up" />
		<label>Channel</label>
		<Select
			v-model="form.channel"
			:options="workspace.channels"
			option-label="display_name"
			option-value="name"
			placeholder="Select assigned number"
			fluid
		/>
		<label>Template</label>
		<Select
			v-model="form.template"
			:options="approvedTemplates"
			option-label="label"
			option-value="name"
			option-disabled="disabled"
			placeholder="Select an approved template"
			fluid
		/>
		<label>Description</label>
		<Textarea
			v-model="form.description"
			rows="3"
			fluid
			placeholder="Purpose and audience notes"
		/>
		<template #footer>
			<Button label="Cancel" text @click="createDialog = false" />
			<Button
				label="Create draft"
				:disabled="!form.title || !form.campaign_key || !form.channel || !form.template"
				:loading="saving"
				@click="createCampaign"
			/>
		</template>
	</Dialog>

	<Dialog
		v-model:visible="authorizationDialog"
		modal
		header="Authorize SEND"
		:style="{ width: '470px' }"
	>
		<div class="authorization-warning">
			<ShieldCheck :size="22" />
			<div>
				<strong>This is independent of Meta template approval.</strong>
				<p>
					{{ selectedCampaign?.recipient_count || 0 }} prepared recipients will become
					eligible to queue.
				</p>
			</div>
		</div>
		<label
			>Type exactly: <code>{{ expectedAuthorization }}</code></label
		>
		<InputText v-model="authorizationText" fluid />
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

<style scoped>
	.metric-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 16px;
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
		color: #8a5b0a;
		background: #fff5d9;
	}

	.metric-icon.scheduled {
		color: #275e9a;
		background: #e7f2ff;
	}

	.metric-icon.delivered {
		color: #087255;
		background: #dff7ed;
	}

	.metric-card small,
	.metric-card strong {
		display: block;
	}

	.metric-card small {
		margin-bottom: 4px;
		color: var(--wa-muted);
		font-size: 10px;
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
		color: #167458;
	}

	.safety-pipeline > div span,
	.safety-pipeline strong,
	.safety-pipeline small {
		display: block;
	}

	.safety-pipeline strong {
		color: #26352f;
		font-size: 10px;
	}

	.safety-pipeline small {
		margin-top: 2px;
		color: #839088;
		font-size: 8px;
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
		font-size: 10px;
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
		color: #087255;
		background: #e3f7ef;
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
		color: #86938c;
		font-size: 8px;
	}

	.count-cell strong {
		font-size: 13px;
	}

	.gate-stack {
		display: grid;
		gap: 5px;
	}

	.gate-stack span {
		color: #9a6a19;
		font-size: 9px;
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
		color: #177657;
	}

	.gate-stack span.passed i {
		background: #23a477;
	}

	.progress-copy {
		display: grid;
		gap: 3px;
		color: #64736c;
		font-size: 9px;
	}

	.progress-copy .failure {
		color: #bf3e42;
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
		color: #819088;
	}

	.empty strong {
		color: #24312c;
	}

	.dialog-note,
	.authorization-warning {
		padding: 12px;
		border-radius: 11px;
		font-size: 11px;
		line-height: 1.5;
	}

	.dialog-note {
		color: #426057;
		background: #eef5f2;
	}

	.authorization-warning {
		display: flex;
		gap: 10px;
		color: #8b4a1a;
		background: #fff4e7;
	}

	.authorization-warning p {
		margin: 3px 0 0;
	}

	label {
		display: block;
		margin: 14px 0 7px;
		font-size: 10px;
		font-weight: 700;
	}

	label code {
		color: #a93236;
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
