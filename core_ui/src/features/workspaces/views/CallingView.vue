<script setup>
	import { onMounted, onUnmounted, ref } from 'vue'
	import Button from 'primevue/button'
	import Checkbox from 'primevue/checkbox'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import Textarea from 'primevue/textarea'
	import ContactSelect from '@/features/contacts/components/ContactSelect.vue'
	import { call, errorMessage, uploadFile } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'
	import { focusDialogControl } from '@/utils/focus'

	const session = useSessionStore(),
		loading = ref(false),
		action = ref(''),
		error = ref(''),
		notice = ref(''),
		account = ref(''),
		showSettings = ref(false),
		showAction = ref(false),
		showOutreach = ref(false)
	const settingsDialog = ref(null)
	const actionDialog = ref(null)
	const outreachDialog = ref(null)
	const workspace = ref({
		accounts: [],
		calls: [],
		templates: [],
		contacts: [],
		settings: {},
		selected_account: '',
	})
	const settingsStatus = ref('DISABLED')
	const settingsJson = ref('{}')
	const form = ref({
		action: 'connect',
		call_id: '',
		identity: '',
		manual_number: '',
		sdp_type: 'offer',
		sdp: '',
		biz_opaque_callback_data: '',
		recording_enabled: false,
		transcription_enabled: false,
		purpose: '',
		announcement_language: 'en_IN',
	})
	const outreach = ref({
		operation: 'button',
		identity: '',
		manual_number: '',
		body_text: 'Call us on WhatsApp for faster support.',
		display_text: 'Call Now',
		template_name: '',
		language_code: 'en',
		ttl_minutes: 10080,
		payload: '',
	})
	const permission = ref({
		identity: '',
		manual_number: '',
		body_text: 'May we call you on WhatsApp?',
	})
	const permissionResult = ref(null)
	const ACTION_FAILED = Symbol('action-failed')
	let unsubscribe = () => {}
	let unsubscribeBatch = () => {}
	let refreshTimer = null
	let loadSequence = 0
	function hasTarget(values) {
		return Boolean(values.identity || values.manual_number?.trim())
	}
	function permissionSummary(result) {
		const value = result?.data?.[0] || result || {}
		return {
			status:
				value.permission_status || value.permission || value.status || 'Response received',
			expiresAt: value.expiration_time || value.expires_at || value.expiration || '',
		}
	}
	async function run(name, task, success = '') {
		action.value = name
		error.value = ''
		notice.value = ''
		try {
			const result = await task()
			notice.value = success
			return result
		} catch (e) {
			error.value = errorMessage(e)
			return ACTION_FAILED
		} finally {
			action.value = ''
		}
	}
	async function load(selected = account.value, { silent = false } = {}) {
		const request = ++loadSequence
		if (!silent) loading.value = true
		error.value = ''
		try {
			const result = await call('frappe_whatsapp_core.calling.calling_workspace', {
				account_name: selected,
			})
			if (request !== loadSequence) return
			workspace.value = result
			account.value = workspace.value.selected_account || ''
			error.value = workspace.value.error || ''
			const calling = {
				...(workspace.value.settings?.calling || workspace.value.settings || {}),
			}
			settingsStatus.value = String(calling.status || 'DISABLED').toUpperCase()
			delete calling.status
			settingsJson.value = JSON.stringify(calling, null, 2)
		} catch (e) {
			if (request === loadSequence) error.value = errorMessage(e)
		} finally {
			if (!silent && request === loadSequence) loading.value = false
		}
	}
	function scheduleRefresh() {
		window.clearTimeout(refreshTimer)
		refreshTimer = window.setTimeout(() => load(account.value, { silent: true }), 180)
	}
	async function saveSettings() {
		let calling
		try {
			calling = JSON.parse(settingsJson.value)
		} catch {
			error.value = 'Advanced calling settings must be valid JSON.'
			return
		}
		if (!calling || Array.isArray(calling) || typeof calling !== 'object') {
			error.value = 'Advanced calling settings must be a JSON object.'
			return
		}
		calling = { ...calling, status: settingsStatus.value }
		const result = await run(
			'settings',
			() =>
				call('frappe_whatsapp_core.calling.update_call_settings', {
					account_name: account.value,
					calling,
				}),
			'Calling settings saved.',
		)
		if (result === ACTION_FAILED) return
		showSettings.value = false
		await load()
	}
	async function checkPermission() {
		permissionResult.value = null
		const result = await run('permission', () =>
			call('frappe_whatsapp_core.calling.get_call_permission', {
				account_name: account.value,
				identity: permission.value.identity || null,
				user_wa_id: permission.value.manual_number || null,
			}),
		)
		if (result === ACTION_FAILED) return
		permissionResult.value = permissionSummary(result)
	}
	async function requestPermission() {
		await run(
			'permission',
			() =>
				call('frappe_whatsapp_core.calling.request_call_permission', {
					account_name: account.value,
					body_text: permission.value.body_text,
					identity: permission.value.identity || null,
					to_number: permission.value.manual_number || null,
				}),
			'Call permission requested.',
		)
	}
	function openAction(row = null) {
		form.value = {
			action: row ? 'pre_accept' : 'connect',
			call_id: row?.call_id || '',
			identity: '',
			manual_number: '',
			sdp_type: row ? 'answer' : 'offer',
			sdp: '',
			biz_opaque_callback_data: '',
			recording_enabled: false,
			transcription_enabled: false,
			purpose: '',
			announcement_language: 'en_IN',
		}
		showAction.value = true
	}
	async function executeAction() {
		const {
			recording_enabled,
			transcription_enabled,
			purpose,
			announcement_language,
			manual_number,
			...values
		} = form.value
		if (!['connect', 'pre_accept', 'accept'].includes(values.action)) {
			values.sdp_type = null
			values.sdp = null
		}
		if (['connect', 'accept'].includes(values.action) && recording_enabled)
			values.recording = { status: 'ENABLED', purpose, announcement_language }
		if (['connect', 'accept'].includes(values.action) && transcription_enabled)
			values.transcription = { status: 'ENABLED', purpose, announcement_language }
		const result = await run(
			'call',
			() =>
				call('frappe_whatsapp_core.calling.call_action', {
					account_name: account.value,
					...values,
					to_number: manual_number || null,
				}),
			`Call action “${values.action}” sent.`,
		)
		if (result === ACTION_FAILED) return
		showAction.value = false
		await load()
	}
	async function sendOutreach() {
		const values = outreach.value
		if (values.operation === 'deep-link') {
			const result = await run('outreach', () =>
				call('frappe_whatsapp_core.calling.build_call_deep_link', {
					account_name: account.value,
					biz_payload: values.payload || null,
				}),
			)
			if (result === ACTION_FAILED) return
			notice.value = result?.url || 'Call deep link generated.'
		} else {
			const method =
				values.operation === 'template' ? 'send_call_button_template' : 'send_call_button'
			const result = await run(
				'outreach',
				() =>
					call(`frappe_whatsapp_core.calling.${method}`, {
						account_name: account.value,
						identity: values.identity || null,
						to_number: values.manual_number || null,
						body_text: values.body_text,
						display_text: values.display_text,
						template_name: values.template_name,
						language_code: values.language_code,
						ttl_minutes: values.ttl_minutes,
						payload: values.payload || null,
					}),
				'Call invitation queued.',
			)
			if (result === ACTION_FAILED) return
		}
		showOutreach.value = false
	}
	async function uploadVoicemail(event) {
		const file = event.target.files?.[0]
		if (!file) return
		const result = await run('voicemail', async () => {
			const stored = await uploadFile(file, true)
			const result = await call(
				'frappe_whatsapp_core.calling.upload_voicemail_announcement',
				{ account_name: account.value, file_url: stored.file_url },
			)
			notice.value = `Voicemail media uploaded: ${result.media_id || ''}`
			return result
		})
		if (result === ACTION_FAILED) return
		event.target.value = ''
	}
	async function openArtifact(mediaId) {
		const result = await run('artifact', () =>
			call('frappe_whatsapp_core.calling.get_call_artifact', {
				account_name: account.value,
				media_id: mediaId,
				download: 1,
			}),
		)
		if (result === ACTION_FAILED) return
		if (result?.file_url) window.open(result.file_url, '_blank', 'noopener')
	}
	onMounted(() => {
		load('')
		unsubscribe = subscribe(session.boot?.site, 'whatsapp_core_call', scheduleRefresh)
		unsubscribeBatch = subscribe(
			session.boot?.site,
			'whatsapp_core_batch_committed',
			(event) => {
				const kinds = Array.isArray(event?.kinds) ? event.kinds : null
				if (!kinds || kinds.includes('call')) scheduleRefresh()
			},
		)
	})
	onUnmounted(() => {
		window.clearTimeout(refreshTimer)
		unsubscribe()
		unsubscribeBatch()
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">WhatsApp Business Calling API</div>
			<h1>Calling</h1>
			<p>
				Manage permissions, Meta signaling and call lifecycle logs. Audio media uses your
				configured WebRTC or SIP infrastructure.
			</p>
		</div>
		<div class="actions">
			<Button
				label="Call invitation"
				icon="pi pi-send"
				outlined
				:disabled="!workspace.available"
				@click="showOutreach = true"
			/>
			<label class="upload-button">
				<input
					type="file"
					accept="audio/ogg,.ogg"
					:disabled="!workspace.available"
					@change="uploadVoicemail"
				/>
				<span class="pi pi-upload" />
				{{ action === 'voicemail' ? 'Uploading…' : 'Voicemail audio' }}
			</label>
			<Button
				label="Settings"
				icon="pi pi-cog"
				outlined
				:disabled="!workspace.available"
				@click="showSettings = true"
			/><Button
				label="Start call"
				icon="pi pi-phone"
				:disabled="!workspace.available"
				@click="openAction()"
			/>
		</div>
	</div>
	<div v-if="error" class="banner error-banner">{{ error }}</div>
	<div v-if="notice" class="banner success-banner">{{ notice }}</div>
	<section class="surface-card panel">
		<div class="toolbar">
			<Select
				v-model="account"
				:options="workspace.accounts"
				option-label="display_name"
				option-value="account_name"
				aria-label="WhatsApp account"
				@change="load($event.value)"
			/><Tag
				:value="settingsStatus === 'ENABLED' ? 'Calling enabled' : 'Calling disabled'"
				:severity="settingsStatus === 'ENABLED' ? 'success' : 'secondary'"
			/><Button
				label="Reload"
				icon="pi pi-refresh"
				severity="secondary"
				outlined
				:loading="loading"
				@click="load()"
			/>
		</div>
		<div class="permission-card">
			<div>
				<strong>Customer call permission</strong
				><small
					>Select a Core contact, then check or request Meta's call permission.</small
				>
			</div>
			<div class="target-fields">
				<ContactSelect
					v-model="permission.identity"
					:options="workspace.contacts || []"
					@update:model-value="permission.manual_number = ''"
				/>
				<span>or</span>
				<InputText
					v-model="permission.manual_number"
					aria-label="WhatsApp number for call permission"
					placeholder="Enter a WhatsApp number"
					@input="permission.identity = ''"
				/>
			</div>
			<Textarea
				v-model="permission.body_text"
				rows="2"
				aria-label="Call permission request message"
				placeholder="Message shown with the call permission request"
			/>
			<div class="actions">
				<Button
					label="Check"
					outlined
					:loading="action === 'permission'"
					:disabled="!hasTarget(permission)"
					@click="checkPermission"
				/><Button
					label="Request"
					:loading="action === 'permission'"
					:disabled="!hasTarget(permission) || !permission.body_text.trim()"
					@click="requestPermission"
				/>
			</div>
		</div>
		<div v-if="permissionResult" class="permission-result">
			<div>
				<small>Current permission</small>
				<strong>{{ permissionResult.status }}</strong>
			</div>
			<span v-if="permissionResult.expiresAt">Expires {{ permissionResult.expiresAt }}</span>
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
			/><Column header="Artifacts"
				><template #body="{ data }"
					><div class="artifact-actions">
						<Button
							v-if="data.recording_media_id"
							label="Recording"
							icon="pi pi-volume-up"
							size="small"
							text
							@click="openArtifact(data.recording_media_id)"
						/><Button
							v-if="data.transcript_media_id"
							label="Transcript"
							icon="pi pi-file"
							size="small"
							text
							@click="openArtifact(data.transcript_media_id)"
						/><span v-if="!data.recording_media_id && !data.transcript_media_id"
							>—</span
						>
					</div></template
				></Column
			><Column header=""
				><template #body="{ data }"
					><Button
						label="Act"
						size="small"
						outlined
						@click="openAction(data)" /></template></Column
			><template #empty
				><div class="empty">No call events received yet.</div></template
			></DataTable
		>
	</section>
	<Dialog
		ref="settingsDialog"
		v-model:visible="showSettings"
		modal
		header="Calling settings"
		:style="{ width: 'min(48rem,calc(100vw - 2rem))' }"
		@show="focusDialogControl(settingsDialog, '[role=combobox]')"
		><div class="form">
			<label
				>Calling availability<Select
					v-model="settingsStatus"
					aria-label="Calling availability"
					:options="[
						{ label: 'Enabled', value: 'ENABLED' },
						{ label: 'Disabled', value: 'DISABLED' },
					]"
					option-label="label"
					option-value="value"
			/></label>
			<p class="help">
				Audio transport and SIP credentials remain on the Integration hub. Core only
				manages the Meta control plane.
			</p>
			<details class="advanced">
				<summary>Advanced Meta settings</summary>
				<p class="help">
					Use this only for provider options not represented above. Enter the fields
					inside Meta's <code>calling</code> object; status is managed separately.
				</p>
				<Textarea
					v-model="settingsJson"
					rows="14"
					aria-label="Advanced Meta calling settings"
					class="json-editor"
				/>
			</details>
		</div>
		<template #footer
			><Button
				label="Cancel"
				severity="secondary"
				outlined
				@click="showSettings = false" /><Button
				label="Save settings"
				:loading="action === 'settings'"
				@click="saveSettings" /></template
	></Dialog>
	<Dialog
		ref="actionDialog"
		v-model:visible="showAction"
		modal
		header="WhatsApp call action"
		:style="{ width: 'min(48rem,calc(100vw - 2rem))' }"
		@show="focusDialogControl(actionDialog, '[role=combobox]')"
		><div class="form">
			<label
				>Action<Select
					v-model="form.action"
					aria-label="WhatsApp call action"
					:options="['connect', 'pre_accept', 'accept', 'reject', 'terminate']"
			/></label>
			<template v-if="form.action === 'connect'">
				<label
					>Contact<ContactSelect
						v-model="form.identity"
						:options="workspace.contacts || []"
						@update:model-value="form.manual_number = ''"
				/></label>
				<label
					>Or enter a WhatsApp number<InputText
						v-model="form.manual_number"
						placeholder="Country code and number"
						@input="form.identity = ''"
				/></label>
			</template>
			<label v-else>Call ID<InputText v-model="form.call_id" /></label>
			<details
				v-if="['connect', 'pre_accept', 'accept'].includes(form.action)"
				class="advanced"
				:open="form.action !== 'connect'"
			>
				<summary>Advanced WebRTC signaling</summary>
				<p class="help">
					Supply the SDP created by your WebRTC/SIP client. Core sends signaling; it does
					not carry call audio.
				</p>
				<div class="form compact-form">
					<label
						>SDP type<Select v-model="form.sdp_type" :options="['offer', 'answer']"
					/></label>
					<label
						>SDP session<Textarea v-model="form.sdp" rows="9" placeholder="v=0…"
					/></label>
					<label
						>Opaque callback data<InputText
							v-model="form.biz_opaque_callback_data"
							maxlength="512"
					/></label>
				</div>
			</details>
			<div v-if="['connect', 'accept'].includes(form.action)" class="consent-grid">
				<label class="check-label">
					<Checkbox v-model="form.recording_enabled" binary /> Record this call
				</label>
				<label class="check-label">
					<Checkbox v-model="form.transcription_enabled" binary /> Transcribe this call
				</label>
				<template v-if="form.recording_enabled || form.transcription_enabled">
					<label class="full-row"
						>Purpose<InputText
							v-model="form.purpose"
							maxlength="250"
							placeholder="Purpose included in Meta's call announcement"
					/></label>
					<label class="full-row"
						>Announcement language<InputText
							v-model="form.announcement_language"
							placeholder="en_IN"
					/></label>
				</template>
			</div>
		</div>
		<template #footer
			><Button
				label="Cancel"
				severity="secondary"
				outlined
				@click="showAction = false" /><Button
				label="Send action"
				:loading="action === 'call'"
				:disabled="
					(form.action === 'connect' ? !hasTarget(form) : !form.call_id) ||
					(['connect', 'pre_accept', 'accept'].includes(form.action) && !form.sdp.trim())
				"
				@click="executeAction" /></template
	></Dialog>
	<Dialog
		ref="outreachDialog"
		v-model:visible="showOutreach"
		modal
		header="WhatsApp call invitation"
		:style="{ width: 'min(42rem,calc(100vw - 2rem))' }"
		@show="focusDialogControl(outreachDialog, '[role=combobox]')"
	>
		<div class="form">
			<label
				>Invitation type<Select
					v-model="outreach.operation"
					aria-label="Call invitation type"
					:options="[
						{ label: 'Session call button', value: 'button' },
						{ label: 'Approved template', value: 'template' },
						{ label: 'Deep link', value: 'deep-link' },
					]"
					option-label="label"
					option-value="value"
			/></label>
			<template v-if="outreach.operation !== 'deep-link'">
				<label
					>Contact<ContactSelect
						v-model="outreach.identity"
						:options="workspace.contacts || []"
						@update:model-value="outreach.manual_number = ''"
				/></label>
				<label
					>Or enter a WhatsApp number<InputText
						v-model="outreach.manual_number"
						placeholder="Country code and number"
						@input="outreach.identity = ''"
				/></label>
			</template>
			<label v-if="outreach.operation === 'button'"
				>Message<Textarea v-model="outreach.body_text" rows="3"
			/></label>
			<label v-if="outreach.operation === 'button'"
				>Button label<InputText v-model="outreach.display_text" maxlength="20"
			/></label>
			<label v-if="outreach.operation === 'template'"
				>Approved template<Select
					v-model="outreach.template_name"
					:options="workspace.templates || []"
					option-label="template_name"
					option-value="template_name"
					filter
					placeholder="Select a synced Meta template"
			/></label>
			<label v-if="outreach.operation === 'template'"
				>Language code<InputText v-model="outreach.language_code"
			/></label>
			<label v-if="outreach.operation !== 'deep-link'"
				>Button TTL (minutes)<InputText
					v-model="outreach.ttl_minutes"
					type="number"
					min="1"
			/></label>
			<label
				>Business payload<InputText
					v-model="outreach.payload"
					placeholder="Optional opaque tracking payload"
			/></label>
		</div>
		<template #footer>
			<Button
				label="Cancel"
				severity="secondary"
				outlined
				@click="showOutreach = false"
			/><Button
				:label="outreach.operation === 'deep-link' ? 'Create link' : 'Send invitation'"
				:loading="action === 'outreach'"
				:disabled="
					(outreach.operation !== 'deep-link' && !hasTarget(outreach)) ||
					(outreach.operation === 'button' && !outreach.body_text.trim()) ||
					(outreach.operation === 'template' && !outreach.template_name)
				"
				@click="sendOutreach"
			/>
		</template>
	</Dialog>
</template>
<style scoped>
	.panel {
		padding: 16px;
		display: grid;
		gap: 16px;
		min-width: 0;
		max-width: 100%;
		overflow: hidden;
	}
	.panel :deep(.p-datatable) {
		min-width: 0;
		max-width: 100%;
	}
	.panel :deep(.p-datatable-table-container) {
		overflow-x: auto;
	}
	.toolbar,
	.actions {
		display: flex;
		gap: 10px;
		align-items: center;
		flex-wrap: wrap;
	}
	.permission-card {
		display: grid;
		grid-template-columns:
			minmax(12rem, 1.1fr) minmax(18rem, 1.7fr) minmax(15rem, 1.3fr)
			auto;
		gap: 10px;
		align-items: center;
		padding: 14px;
		border: 1px solid var(--wa-border);
		border-radius: 14px;
	}
	.permission-card > div:first-child {
		display: grid;
		gap: 4px;
	}
	.target-fields {
		display: grid;
		grid-template-columns: minmax(11rem, 1fr) auto minmax(10rem, 0.8fr);
		gap: 8px;
		align-items: center;
		min-width: 0;
	}
	.target-fields > span {
		color: var(--wa-muted);
		font-size: 11px;
		text-transform: uppercase;
	}
	.permission-result {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		align-items: center;
		padding: 12px 14px;
		border: 1px solid color-mix(in srgb, var(--wa-success, #087f5b) 35%, var(--wa-border));
		border-radius: 12px;
		background: color-mix(in srgb, var(--wa-success, #087f5b) 8%, transparent);
	}
	.permission-result > div {
		display: grid;
		gap: 2px;
	}
	.permission-result small,
	.permission-result span {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.permission-card small,
	.help {
		color: var(--wa-muted);
	}
	.form {
		display: grid;
		gap: 14px;
	}
	.form label {
		display: grid;
		gap: 6px;
		font-size: 12px;
	}
	.compact-form {
		margin-top: 12px;
	}
	.advanced {
		padding: 12px;
		border: 1px solid var(--wa-border);
		border-radius: 12px;
	}
	.advanced summary {
		cursor: pointer;
		font-size: 13px;
		font-weight: 650;
	}
	.advanced .help {
		margin: 10px 0;
	}
	.consent-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
		padding: 12px;
		border: 1px solid var(--wa-border);
		border-radius: 12px;
	}
	.consent-grid .check-label {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.full-row {
		grid-column: 1 / -1;
	}
	.artifact-actions {
		display: flex;
		gap: 4px;
		align-items: center;
		flex-wrap: wrap;
	}
	.upload-button {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		min-height: 40px;
		padding: 0 14px;
		border: 1px solid var(--wa-border);
		border-radius: 8px;
		cursor: pointer;
		font-size: 14px;
		font-weight: 600;
	}
	.upload-button input {
		display: none;
	}
	.json-editor {
		width: 100%;
		font-family: ui-monospace, SFMono-Regular, monospace;
	}
	.banner {
		padding: 10px 14px;
		margin-bottom: 12px;
		border-radius: 10px;
	}
	.error-banner {
		background: color-mix(in srgb, var(--wa-danger, #c92a2a) 10%, var(--wa-surface));
		color: var(--wa-danger, #c92a2a);
		border: 1px solid color-mix(in srgb, var(--wa-danger, #c92a2a) 28%, var(--wa-border));
	}
	.success-banner {
		background: color-mix(in srgb, var(--wa-success, #087f5b) 10%, var(--wa-surface));
		color: var(--wa-success, #087f5b);
		border: 1px solid color-mix(in srgb, var(--wa-success, #087f5b) 28%, var(--wa-border));
		overflow-wrap: anywhere;
	}
	.empty {
		padding: 48px;
		text-align: center;
		color: var(--wa-muted);
	}
	@media (max-width: 1100px) {
		.permission-card {
			grid-template-columns: 1fr 1fr;
		}
		.permission-card > div:first-child,
		.permission-card > textarea {
			grid-column: 1/-1;
		}
		.permission-card > .target-fields {
			grid-column: auto;
		}
	}
	@media (max-width: 600px) {
		.toolbar,
		.permission-card {
			align-items: stretch;
			grid-template-columns: 1fr;
		}
		.permission-card > * {
			grid-column: 1 !important;
		}
		.target-fields {
			grid-template-columns: 1fr;
		}
		.target-fields > span {
			display: none;
		}
		.permission-result {
			align-items: flex-start;
			flex-direction: column;
		}
		.consent-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
