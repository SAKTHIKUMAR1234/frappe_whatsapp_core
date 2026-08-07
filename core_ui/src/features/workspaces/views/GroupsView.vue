<script setup>
	import { computed, onMounted, onUnmounted, ref } from 'vue'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import MultiSelect from 'primevue/multiselect'
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import Textarea from 'primevue/textarea'
	import { MessageCircleMore, Settings2, ShieldCheck, UsersRound } from 'lucide-vue-next'
	import { call, errorMessage, uploadFile } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'

	const session = useSessionStore()
	const loading = ref(false),
		saving = ref(false),
		action = ref(''),
		showCreate = ref(false),
		showManage = ref(false),
		error = ref(''),
		notice = ref('')
	const workspace = ref({
		accounts: [],
		data: [],
		templates: [],
		contacts: [],
		selected_account: '',
	})
	const account = ref(''),
		selected = ref(null),
		inviteLink = ref(''),
		joinRequests = ref([]),
		selectedRequests = ref([]),
		participantsToRemove = ref([]),
		messageType = ref('text'),
		messageBody = ref(''),
		messageFileUrl = ref(''),
		messageFilename = ref(''),
		messageTemplate = ref(''),
		messageLanguage = ref('en'),
		messageId = ref(''),
		pinOperation = ref('pin'),
		pinDays = ref(7),
		activity = ref({ group: null, members: [], receipts: [] })
	const form = ref({ subject: '', description: '', join_approval_mode: 'auto_approve' })
	const edit = ref({ subject: '', description: '' })
	const invite = ref({ identity: '', template_name: '', language_code: 'en' })
	const rows = computed(() => workspace.value.data || [])
	const ACTION_FAILED = Symbol('action-failed')
	let unsubscribe = () => {}
	let realtimeRefresh = null

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
	async function load(selectedAccount = account.value, { silent = false } = {}) {
		if (!silent) loading.value = true
		error.value = ''
		try {
			workspace.value = await call('frappe_whatsapp_core.groups.group_workspace', {
				account_name: selectedAccount,
			})
			account.value = workspace.value.selected_account || ''
			error.value = workspace.value.error || ''
		} catch (e) {
			error.value = errorMessage(e)
		} finally {
			if (!silent) loading.value = false
		}
	}
	async function create() {
		saving.value = true
		try {
			const result = await run(
				'create',
				() =>
					call('frappe_whatsapp_core.groups.create_group', {
						account_name: account.value,
						...form.value,
					}),
				'Group created.',
			)
			if (result === ACTION_FAILED) return
			showCreate.value = false
			form.value = { subject: '', description: '', join_approval_mode: 'auto_approve' }
			await load()
		} finally {
			saving.value = false
		}
	}
	async function manage(group) {
		selected.value = group
		edit.value = { subject: group.subject || '', description: group.description || '' }
		inviteLink.value = ''
		joinRequests.value = []
		selectedRequests.value = []
		showManage.value = true
		const detail = await run('details', () =>
			call('frappe_whatsapp_core.groups.get_group', {
				account_name: account.value,
				group_id: group.id,
			}),
		)
		if (detail === ACTION_FAILED) return
		selected.value = detail?.data?.[0] || detail || group
		edit.value = {
			subject: selected.value.subject || '',
			description: selected.value.description || '',
		}
		await loadActivity()
	}
	async function loadActivity() {
		const result = await run('activity', () =>
			call('frappe_whatsapp_core.groups.group_activity', {
				group_id: selected.value.id,
			}),
		)
		if (result !== ACTION_FAILED) activity.value = result
	}
	async function saveGroup() {
		const result = await run(
			'save',
			() =>
				call('frappe_whatsapp_core.groups.update_group', {
					account_name: account.value,
					group_id: selected.value.id,
					...edit.value,
				}),
			'Group details updated.',
		)
		if (result === ACTION_FAILED) return
		selected.value = { ...selected.value, ...edit.value }
		await load(account.value, { silent: true })
	}
	async function loadInvite(reset = false) {
		const method = reset ? 'reset_invite_link' : 'get_invite_link'
		const result = await run(
			'invite',
			() =>
				call(`frappe_whatsapp_core.groups.${method}`, {
					account_name: account.value,
					group_id: selected.value.id,
				}),
			reset ? 'Invite link reset.' : '',
		)
		if (result === ACTION_FAILED) return
		inviteLink.value =
			result?.invite_link || result?.data?.[0]?.invite_link || result?.link || ''
	}
	async function loadRequests() {
		const result = await run('requests', () =>
			call('frappe_whatsapp_core.groups.list_join_requests', {
				account_name: account.value,
				group_id: selected.value.id,
			}),
		)
		if (result === ACTION_FAILED) return
		joinRequests.value = result?.data || []
		selectedRequests.value = []
	}
	async function decide(approve) {
		const result = await run(
			'requests',
			() =>
				call('frappe_whatsapp_core.groups.change_join_requests', {
					account_name: account.value,
					group_id: selected.value.id,
					join_requests: selectedRequests.value,
					approve: approve ? 1 : 0,
				}),
			approve ? 'Requests approved.' : 'Requests rejected.',
		)
		if (result === ACTION_FAILED) return
		await loadRequests()
	}
	async function removeParticipants() {
		const result = await run(
			'remove',
			() =>
				call('frappe_whatsapp_core.groups.remove_participants', {
					account_name: account.value,
					group_id: selected.value.id,
					participants: participantsToRemove.value,
				}),
			'Participants removed.',
		)
		if (result === ACTION_FAILED) return
		participantsToRemove.value = []
		await loadActivity()
	}
	async function sendMessage() {
		let content
		if (messageType.value === 'text') content = { body: messageBody.value }
		else if (messageType.value === 'template') {
			content = {
				name: messageTemplate.value,
				language: { code: messageLanguage.value || 'en' },
			}
		} else {
			content = { file_url: messageFileUrl.value }
			if (messageBody.value && messageType.value !== 'audio')
				content.caption = messageBody.value
			if (messageType.value === 'document' && messageFilename.value)
				content.filename = messageFilename.value
		}
		const result = await run(
			'send',
			() =>
				call('frappe_whatsapp_core.groups.send_group_message', {
					account_name: account.value,
					group_id: selected.value.id,
					message_type: messageType.value,
					content,
				}),
			'Message queued in the shared inbox.',
		)
		if (result === ACTION_FAILED) return
		messageBody.value = ''
		messageFileUrl.value = ''
		messageFilename.value = ''
	}
	async function selectMessageFile(event) {
		const file = event.target.files?.[0]
		if (!file) return
		const result = await run(
			'message-upload',
			async () => {
				const stored = await uploadFile(file, true)
				messageFileUrl.value = stored.file_url
				messageFilename.value = file.name
				return stored
			},
			'File ready to send.',
		)
		if (result === ACTION_FAILED) return
		event.target.value = ''
	}
	async function sendInvite() {
		const result = await run(
			'send-invite',
			() =>
				call('frappe_whatsapp_core.groups.send_group_invite_template', {
					account_name: account.value,
					group_id: selected.value.id,
					...invite.value,
				}),
			'Group invite queued.',
		)
		if (result === ACTION_FAILED) return
		invite.value.identity = ''
	}
	async function pinMessage() {
		await run(
			'pin',
			() =>
				call('frappe_whatsapp_core.groups.pin_group_message', {
					account_name: account.value,
					group_id: selected.value.id,
					message_id: messageId.value,
					operation: pinOperation.value,
					expiration_days: pinOperation.value === 'pin' ? pinDays.value : null,
				}),
			`Message ${pinOperation.value === 'pin' ? 'pinned' : 'unpinned'}.`,
		)
	}
	async function uploadPicture(event) {
		const file = event.target.files?.[0]
		if (!file) return
		const content = await new Promise((resolve, reject) => {
			const reader = new FileReader()
			reader.onload = () => resolve(String(reader.result).split(',')[1])
			reader.onerror = reject
			reader.readAsDataURL(file)
		})
		await run(
			'picture',
			() =>
				call('frappe_whatsapp_core.groups.update_group_picture', {
					account_name: account.value,
					group_id: selected.value.id,
					file_content_b64: content,
					filename: file.name,
				}),
			'Group picture updated.',
		)
	}
	async function deleteGroup() {
		if (!window.confirm(`Delete ${selected.value.subject || selected.value.id}?`)) return
		const result = await run(
			'delete',
			() =>
				call('frappe_whatsapp_core.groups.delete_group', {
					account_name: account.value,
					group_id: selected.value.id,
				}),
			'Group deleted.',
		)
		if (result === ACTION_FAILED) return
		showManage.value = false
		await load()
	}
	function groupSeverity(group) {
		if (group.status === 'Active') return 'success'
		if (group.status === 'Failed') return 'danger'
		if (group.status === 'Suspended') return 'warn'
		return 'secondary'
	}
	function queueRealtimeRefresh(event) {
		window.clearTimeout(realtimeRefresh)
		realtimeRefresh = window.setTimeout(async () => {
			await load(account.value, { silent: true })
			if (showManage.value && selected.value?.id === event?.group_id) await loadActivity()
		}, 200)
	}
	onMounted(() => {
		load('')
		unsubscribe = subscribe(session.boot?.site, 'whatsapp_core_group', queueRealtimeRefresh)
	})
	onUnmounted(() => {
		window.clearTimeout(realtimeRefresh)
		unsubscribe()
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Meta Groups API</div>
			<h1>WhatsApp Groups</h1>
			<p>Create, moderate and message Meta-hosted business groups without leaving Core.</p>
		</div>
		<Button
			label="Create group"
			icon="pi pi-plus"
			:disabled="!workspace.available"
			@click="showCreate = true"
		/>
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
			/><Button
				label="Reload"
				icon="pi pi-refresh"
				severity="secondary"
				outlined
				:loading="loading"
				@click="load()"
			/>
		</div>
		<div v-if="loading" class="group-grid" aria-busy="true">
			<div v-for="index in 4" :key="index" class="group-card loading-card"></div>
		</div>
		<div v-else-if="rows.length" class="group-grid">
			<article v-for="group in rows" :key="group.id" class="group-card">
				<header>
					<span class="group-avatar"><UsersRound :size="18" /></span>
					<div>
						<strong>{{ group.subject || 'Untitled group' }}</strong>
						<small>{{ group.id }}</small>
					</div>
					<Tag
						:value="group.status || 'Active'"
						:severity="groupSeverity(group)"
						rounded
					/>
				</header>
				<p>{{ group.description || 'No group description has been added.' }}</p>
				<div class="group-facts">
					<span
						><UsersRound :size="14" />{{
							group.total_participant_count || 0
						}}
						participants</span
					>
					<span
						><ShieldCheck :size="14" />{{
							group.join_approval_mode || 'Automatic approval'
						}}</span
					>
				</div>
				<Button label="Manage group" outlined fluid @click="manage(group)">
					<template #icon><Settings2 :size="15" /></template>
				</Button>
			</article>
		</div>
		<div v-else class="empty">
			<MessageCircleMore :size="32" />
			<strong>No WhatsApp groups yet</strong>
			<span>Create the first group for this account or choose another account.</span>
		</div>
	</section>
	<Dialog
		v-model:visible="showCreate"
		modal
		header="Create WhatsApp group"
		:style="{ width: 'min(34rem, 94vw)' }"
		><div class="form">
			<label>Subject<InputText v-model="form.subject" maxlength="128" /></label
			><label
				>Description<Textarea
					v-model="form.description"
					rows="4"
					maxlength="2048" /></label
			><label
				>Join approval<Select
					v-model="form.join_approval_mode"
					:options="[
						{ label: 'Automatic', value: 'auto_approve' },
						{ label: 'Approval required', value: 'approval_required' },
					]"
					option-label="label"
					option-value="value"
			/></label>
		</div>
		<template #footer
			><Button
				label="Cancel"
				severity="secondary"
				outlined
				@click="showCreate = false" /><Button
				label="Create"
				:loading="saving"
				:disabled="!form.subject.trim()"
				@click="create" /></template
	></Dialog>
	<Dialog
		v-model:visible="showManage"
		modal
		:header="selected?.subject || 'Manage group'"
		:style="{ width: 'min(76rem, calc(100vw - 2rem))' }"
		:content-style="{ maxHeight: 'calc(100vh - 11rem)', overflow: 'auto' }"
	>
		<div v-if="selected" class="manage-grid">
			<section class="group-summary">
				<span class="group-avatar"><UsersRound :size="18" /></span>
				<div>
					<strong>{{ selected.subject }}</strong>
					<small
						>{{ selected.id }} ·
						{{ selected.total_participant_count || 0 }} participants</small
					>
				</div>
				<Tag
					:value="selected.status || 'Active'"
					:severity="groupSeverity(selected)"
					rounded
				/>
			</section>
			<section class="manage-card">
				<h3>Group details</h3>
				<div class="form">
					<label>Subject<InputText v-model="edit.subject" /></label
					><label>Description<Textarea v-model="edit.description" rows="3" /></label
					><label
						>Picture<input type="file" accept="image/*" @change="uploadPicture"
					/></label>
					<div class="actions">
						<Button
							label="Save details"
							:loading="action === 'save'"
							@click="saveGroup"
						/><Button
							label="Delete group"
							severity="danger"
							outlined
							:loading="action === 'delete'"
							@click="deleteGroup"
						/>
					</div>
				</div>
			</section>
			<section class="manage-card">
				<h3>Invite and approvals</h3>
				<div class="actions">
					<Button
						label="Get invite link"
						outlined
						:loading="action === 'invite'"
						@click="loadInvite(false)"
					/><Button
						label="Reset link"
						severity="secondary"
						outlined
						:loading="action === 'invite'"
						@click="loadInvite(true)"
					/><Button
						label="Join requests"
						outlined
						:loading="action === 'requests'"
						@click="loadRequests"
					/>
				</div>
				<InputText
					v-if="inviteLink"
					:model-value="inviteLink"
					readonly
					class="wide"
				/><DataTable
					v-if="joinRequests.length"
					v-model:selection="selectedRequests"
					:value="joinRequests"
					data-key="id"
					size="small"
					><Column selection-mode="multiple" /><Column
						field="id"
						header="Request" /><Column field="user_wa_id" header="WhatsApp ID"
				/></DataTable>
				<div v-if="joinRequests.length" class="actions">
					<Button
						label="Approve"
						:disabled="!selectedRequests.length"
						@click="decide(true)"
					/><Button
						label="Reject"
						severity="danger"
						outlined
						:disabled="!selectedRequests.length"
						@click="decide(false)"
					/>
				</div>
				<div class="form invite-form">
					<label>
						Recipient contact
						<Select
							v-model="invite.identity"
							:options="workspace.contacts || []"
							option-label="label"
							option-value="identity"
							filter
							placeholder="Select a Core contact"
						>
							<template #option="{ option }">
								<div class="contact-option">
									<strong>{{ option.label }}</strong>
									<small
										>{{ option.phone_number }} · {{ option.reference }}</small
									>
								</div>
							</template>
						</Select>
					</label>
					<label
						>Approved invite template<Select
							v-model="invite.template_name"
							:options="workspace.templates || []"
							option-label="template_name"
							option-value="template_name"
							filter
							placeholder="Select a synced Meta template"
					/></label>
					<label>Language<InputText v-model="invite.language_code" /></label>
					<Button
						label="Send approved invite"
						icon="pi pi-send"
						:loading="action === 'send-invite'"
						:disabled="!invite.identity || !invite.template_name.trim()"
						@click="sendInvite"
					/>
				</div>
			</section>
			<section class="manage-card">
				<h3>Participants</h3>
				<div v-if="activity.members.length" class="activity-list">
					<div v-for="member in activity.members" :key="member.participant_id">
						<span>{{ member.participant_id }}</span
						><strong>{{ member.status }}</strong>
					</div>
				</div>
				<label>
					Participants to remove
					<MultiSelect
						v-model="participantsToRemove"
						:options="activity.members"
						option-label="participant_id"
						option-value="participant_id"
						filter
						display="chip"
						placeholder="Choose participants"
					/>
				</label>
				<Button
					label="Remove participants"
					severity="danger"
					outlined
					:disabled="!participantsToRemove.length"
					:loading="action === 'remove'"
					@click="removeParticipants"
				/>
			</section>
			<section class="manage-card">
				<h3>Message group</h3>
				<label
					>Message type<Select
						v-model="messageType"
						:options="['text', 'image', 'video', 'audio', 'document', 'template']"
				/></label>
				<template v-if="messageType === 'template'">
					<label
						>Approved template<Select
							v-model="messageTemplate"
							:options="workspace.templates || []"
							option-label="template_name"
							option-value="template_name"
							filter
							placeholder="Select a synced Meta template"
					/></label>
					<label>Language code<InputText v-model="messageLanguage" /></label>
				</template>
				<template v-else-if="messageType !== 'text'">
					<label class="file-input"
						>Media file<input
							type="file"
							:accept="
								messageType === 'image'
									? 'image/*'
									: messageType === 'video'
										? 'video/*'
										: messageType === 'audio'
											? 'audio/*'
											: '*/*'
							"
							@change="selectMessageFile"
					/></label>
					<small v-if="messageFileUrl" class="file-ready">
						{{ messageFilename }} is ready.
					</small>
				</template>
				<label v-if="!['template', 'audio'].includes(messageType)"
					>{{ messageType === 'text' ? 'Message' : 'Caption'
					}}<Textarea v-model="messageBody" rows="3" /></label
				><Button
					label="Send message"
					icon="pi pi-send"
					:disabled="
						messageType === 'text'
							? !messageBody.trim()
							: messageType === 'template'
								? !messageTemplate.trim()
								: !messageFileUrl
					"
					:loading="action === 'send'"
					@click="sendMessage"
				/>
				<div class="pin-row">
					<InputText v-model="messageId" placeholder="Message ID" /><Select
						v-model="pinOperation"
						:options="[
							{ label: 'Pin', value: 'pin' },
							{ label: 'Unpin', value: 'unpin' },
						]"
						option-label="label"
						option-value="value"
					/><InputText
						v-if="pinOperation === 'pin'"
						v-model="pinDays"
						type="number"
						min="1"
						placeholder="Days"
					/><Button
						label="Apply"
						outlined
						:disabled="!messageId.trim()"
						:loading="action === 'pin'"
						@click="pinMessage"
					/>
				</div>
				<div v-if="activity.receipts.length" class="receipt-summary">
					<strong>Recent participant receipts</strong>
					<span
						v-for="receipt in activity.receipts.slice(0, 8)"
						:key="`${receipt.message}-${receipt.participant_id}`"
					>
						{{ receipt.participant_id }} · {{ receipt.status }}
					</span>
				</div>
			</section>
		</div>
	</Dialog>
</template>
<style scoped>
	.panel {
		padding: 16px;
		display: grid;
		gap: 14px;
	}
	.group-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
	}
	.group-card {
		display: grid;
		gap: 13px;
		padding: 15px;
		border: 1px solid var(--wa-border);
		border-radius: 14px;
		background: var(--wa-surface);
	}
	.group-card header,
	.group-summary {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 10px;
	}
	.group-card header strong,
	.group-card header small,
	.group-summary strong,
	.group-summary small {
		display: block;
	}
	.group-card header small,
	.group-summary small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 10px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.group-avatar {
		display: grid;
		width: 34px;
		height: 34px;
		place-items: center;
		border-radius: 10px;
		color: #0b7258;
		background: #e5f7f0;
	}
	.group-card p {
		min-height: 32px;
		margin: 0;
		color: var(--wa-muted);
		font-size: 11px;
		line-height: 1.45;
	}
	.group-facts {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 14px;
		color: var(--wa-muted);
		font-size: 10px;
	}
	.group-facts span {
		display: flex;
		align-items: center;
		gap: 5px;
	}
	.loading-card {
		height: 190px;
		background: linear-gradient(
			90deg,
			var(--wa-surface) 20%,
			#eef4f1 50%,
			var(--wa-surface) 80%
		);
		background-size: 200% 100%;
		animation: group-pulse 1.3s ease-in-out infinite;
	}
	@keyframes group-pulse {
		to {
			background-position: -200% 0;
		}
	}
	.toolbar,
	.actions,
	.pin-row {
		display: flex;
		gap: 10px;
		align-items: center;
		flex-wrap: wrap;
	}
	.toolbar {
		justify-content: space-between;
	}
	.form,
	.manage-card {
		display: grid;
		gap: 14px;
	}
	.form label,
	.manage-card label {
		display: grid;
		gap: 6px;
		font-size: 12px;
	}
	.manage-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
	}
	.group-summary {
		grid-column: 1 / -1;
		padding: 14px 16px;
		border: 1px solid var(--wa-border);
		border-radius: 14px;
		background: var(--wa-surface-soft, #f7faf8);
	}
	.manage-card {
		padding: 16px;
		border: 1px solid var(--wa-border);
		border-radius: 14px;
		align-content: start;
	}
	.manage-card h3 {
		margin: 0;
	}
	.invite-form {
		padding-top: 12px;
		border-top: 1px solid var(--wa-border);
	}
	.activity-list,
	.receipt-summary {
		display: grid;
		gap: 8px;
		font-size: 12px;
	}
	.file-input input {
		padding: 8px;
		border: 1px solid var(--wa-border);
		border-radius: 8px;
	}
	.file-ready {
		color: var(--wa-success, #087f5b);
	}
	.contact-option strong,
	.contact-option small {
		display: block;
	}
	.contact-option strong {
		font-size: 12px;
	}
	.contact-option small {
		margin-top: 2px;
		color: var(--wa-muted);
		font-size: 10px;
	}
	.activity-list > div {
		display: flex;
		justify-content: space-between;
		gap: 12px;
	}
	.wide {
		width: 100%;
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
	}
	.empty {
		display: grid;
		gap: 7px;
		justify-items: center;
		padding: 48px;
		text-align: center;
		color: #7d8983;
	}
	@media (max-width: 760px) {
		.manage-grid,
		.group-grid {
			grid-template-columns: 1fr;
		}
		.toolbar {
			align-items: stretch;
			flex-direction: column;
		}
		.pin-row > * {
			width: 100%;
		}
	}
</style>
