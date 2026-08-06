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
	import { call, errorMessage, uploadFile } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'

	const session = useSessionStore(),
		loading = ref(false),
		action = ref(''),
		error = ref(''),
		notice = ref(''),
		account = ref(''),
		showSettings = ref(false),
		showAction = ref(false),
		showOutreach = ref(false)
	const workspace = ref({ accounts: [], calls: [], settings: {}, selected_account: '' })
	const settingsJson = ref('{}')
	const form = ref({
		action: 'connect',
		call_id: '',
		to_number: '',
		recipient: '',
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
		to_number: '',
		recipient: '',
		body_text: 'Call us on WhatsApp for faster support.',
		display_text: 'Call Now',
		template_name: '',
		language_code: 'en',
		ttl_minutes: 10080,
		payload: '',
	})
	const permission = ref({
		user_wa_id: '',
		recipient: '',
		body_text: 'May we call you on WhatsApp?',
	})
	let unsubscribe = () => {}
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
			throw e
		} finally {
			action.value = ''
		}
	}
	async function load(selected = account.value) {
		loading.value = true
		error.value = ''
		try {
			workspace.value = await call('frappe_whatsapp_core.calling.calling_workspace', {
				account_name: selected,
			})
			account.value = workspace.value.selected_account
			settingsJson.value = JSON.stringify(
				workspace.value.settings?.calling || workspace.value.settings || {},
				null,
				2,
			)
		} catch (e) {
			error.value = errorMessage(e)
		} finally {
			loading.value = false
		}
	}
	async function saveSettings() {
		let calling
		try {
			calling = JSON.parse(settingsJson.value)
		} catch {
			error.value = 'Calling settings must be valid JSON.'
			return
		}
		await run(
			'settings',
			() =>
				call('frappe_whatsapp_core.calling.update_call_settings', {
					account_name: account.value,
					calling,
				}),
			'Calling settings saved.',
		)
		showSettings.value = false
		await load()
	}
	async function checkPermission() {
		const result = await run('permission', () =>
			call('frappe_whatsapp_core.calling.get_call_permission', {
				account_name: account.value,
				user_wa_id: permission.value.user_wa_id || null,
				recipient: permission.value.recipient || null,
			}),
		)
		notice.value = JSON.stringify(result)
	}
	async function requestPermission() {
		await run(
			'permission',
			() =>
				call('frappe_whatsapp_core.calling.request_call_permission', {
					account_name: account.value,
					body_text: permission.value.body_text,
					to_number: permission.value.user_wa_id || null,
					recipient: permission.value.recipient || null,
				}),
			'Call permission requested.',
		)
	}
	function openAction(row = null) {
		form.value = {
			action: row ? 'pre_accept' : 'connect',
			call_id: row?.call_id || '',
			to_number: '',
			recipient: '',
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
		await run(
			'call',
			() =>
				call('frappe_whatsapp_core.calling.call_action', {
					account_name: account.value,
					...values,
				}),
			`Call action “${values.action}” sent.`,
		)
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
			notice.value = result?.url || 'Call deep link generated.'
		} else {
			const method =
				values.operation === 'template' ? 'send_call_button_template' : 'send_call_button'
			await run(
				'outreach',
				() =>
					call(`frappe_whatsapp_core.calling.${method}`, {
						account_name: account.value,
						to_number: values.to_number || null,
						recipient: values.recipient || null,
						body_text: values.body_text,
						display_text: values.display_text,
						template_name: values.template_name,
						language_code: values.language_code,
						ttl_minutes: values.ttl_minutes,
						payload: values.payload || null,
					}),
				'Call invitation queued.',
			)
		}
		showOutreach.value = false
	}
	async function uploadVoicemail(event) {
		const file = event.target.files?.[0]
		if (!file) return
		await run('voicemail', async () => {
			const stored = await uploadFile(file, true)
			const result = await call(
				'frappe_whatsapp_core.calling.upload_voicemail_announcement',
				{ account_name: account.value, file_url: stored.file_url },
			)
			notice.value = `Voicemail media uploaded: ${result.media_id || ''}`
			return result
		})
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
		if (result?.file_url) window.open(result.file_url, '_blank', 'noopener')
	}
	onMounted(() => {
		load('')
		unsubscribe = subscribe(session.boot?.site, 'whatsapp_core_call', () => load())
	})
	onUnmounted(() => unsubscribe())
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
				@click="showOutreach = true"
			/>
			<label class="upload-button">
				<input type="file" accept="audio/ogg,.ogg" @change="uploadVoicemail" />
				<span class="pi pi-upload" />
				{{ action === 'voicemail' ? 'Uploading…' : 'Voicemail audio' }}
			</label>
			<Button
				label="Settings"
				icon="pi pi-cog"
				outlined
				@click="showSettings = true"
			/><Button label="Start call" icon="pi pi-phone" @click="openAction()" />
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
				@change="load($event.value)"
			/><Tag
				:value="workspace.settings?.calling?.status || 'Not configured'"
				severity="info"
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
					>Check the current permission or send Meta's permission request message.</small
				>
			</div>
			<InputText v-model="permission.user_wa_id" placeholder="WhatsApp number" /><InputText
				v-model="permission.recipient"
				placeholder="Recipient ID (optional)"
			/><Textarea v-model="permission.body_text" rows="2" />
			<div class="actions">
				<Button
					label="Check"
					outlined
					:loading="action === 'permission'"
					:disabled="!permission.user_wa_id && !permission.recipient"
					@click="checkPermission"
				/><Button
					label="Request"
					:loading="action === 'permission'"
					:disabled="
						(!permission.user_wa_id && !permission.recipient) || !permission.body_text
					"
					@click="requestPermission"
				/>
			</div>
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
		v-model:visible="showSettings"
		modal
		header="Calling settings"
		:style="{ width: 'min(48rem,calc(100vw - 2rem))' }"
		><p class="help">
			Edit the Meta <code>calling</code> settings object. SIP credentials remain on the
			integration hub.
		</p>
		<Textarea v-model="settingsJson" rows="18" class="json-editor" /><template #footer
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
		v-model:visible="showAction"
		modal
		header="WhatsApp call action"
		:style="{ width: 'min(48rem,calc(100vw - 2rem))' }"
		><div class="form">
			<label
				>Action<Select
					v-model="form.action"
					:options="['connect', 'pre_accept', 'accept', 'reject', 'terminate']" /></label
			><label v-if="form.action === 'connect'"
				>WhatsApp number<InputText v-model="form.to_number" /></label
			><label v-if="form.action === 'connect'"
				>Recipient ID (optional)<InputText v-model="form.recipient" /></label
			><label v-else>Call ID<InputText v-model="form.call_id" /></label
			><template v-if="['connect', 'pre_accept', 'accept'].includes(form.action)"
				><label
					>SDP type<Select
						v-model="form.sdp_type"
						:options="['offer', 'answer']" /></label
				><label
					>SDP session<Textarea
						v-model="form.sdp"
						rows="10"
						placeholder="v=0…" /></label></template
			><label
				>Opaque callback data<InputText
					v-model="form.biz_opaque_callback_data"
					maxlength="512"
			/></label>
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
					form.action === 'connect' ? !form.to_number && !form.recipient : !form.call_id
				"
				@click="executeAction" /></template
	></Dialog>
	<Dialog
		v-model:visible="showOutreach"
		modal
		header="WhatsApp call invitation"
		:style="{ width: 'min(42rem,calc(100vw - 2rem))' }"
	>
		<div class="form">
			<label
				>Invitation type<Select
					v-model="outreach.operation"
					:options="[
						{ label: 'Session call button', value: 'button' },
						{ label: 'Approved template', value: 'template' },
						{ label: 'Deep link', value: 'deep-link' },
					]"
					option-label="label"
					option-value="value"
			/></label>
			<template v-if="outreach.operation !== 'deep-link'">
				<label>WhatsApp number<InputText v-model="outreach.to_number" /></label>
				<label>Recipient ID (optional)<InputText v-model="outreach.recipient" /></label>
			</template>
			<label v-if="outreach.operation === 'button'"
				>Message<Textarea v-model="outreach.body_text" rows="3"
			/></label>
			<label v-if="outreach.operation === 'button'"
				>Button label<InputText v-model="outreach.display_text" maxlength="20"
			/></label>
			<label v-if="outreach.operation === 'template'"
				>Template name<InputText v-model="outreach.template_name"
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
					outreach.operation !== 'deep-link' &&
					!outreach.to_number &&
					!outreach.recipient
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
			minmax(12rem, 1.2fr) repeat(2, minmax(10rem, 1fr)) minmax(15rem, 1.5fr)
			auto;
		gap: 10px;
		align-items: center;
		padding: 14px;
		border: 1px solid var(--wa-border);
		border-radius: 14px;
	}
	.permission-card div:first-child {
		display: grid;
		gap: 4px;
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
		background: #fff1f1;
		color: #a52222;
	}
	.success-banner {
		background: #e8f8f1;
		color: #076445;
		overflow-wrap: anywhere;
	}
	.empty {
		padding: 48px;
		text-align: center;
		color: #7d8983;
	}
	@media (max-width: 1100px) {
		.permission-card {
			grid-template-columns: 1fr 1fr;
		}
		.permission-card > div:first-child,
		.permission-card > textarea {
			grid-column: 1/-1;
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
		.consent-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
