<script setup>
	import { computed, onMounted, ref } from 'vue'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import { call, errorMessage } from '@/services/frappe'

	const loading = ref(false),
		saving = ref(false),
		action = ref(''),
		showCreate = ref(false),
		showManage = ref(false),
		error = ref(''),
		notice = ref('')
	const workspace = ref({ accounts: [], data: [], selected_account: '' })
	const account = ref(''),
		selected = ref(null),
		inviteLink = ref(''),
		joinRequests = ref([]),
		selectedRequests = ref([]),
		participantsToRemove = ref(''),
		messageBody = ref(''),
		messageId = ref(''),
		pinOperation = ref('pin'),
		pinDays = ref(7)
	const form = ref({ subject: '', description: '', join_approval_mode: 'auto_approve' })
	const edit = ref({ subject: '', description: '' })
	const rows = computed(() => workspace.value.data || [])

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
	async function load(selectedAccount = account.value) {
		loading.value = true
		error.value = ''
		try {
			workspace.value = await call('frappe_whatsapp_core.groups.group_workspace', {
				account_name: selectedAccount,
			})
			account.value = workspace.value.selected_account
		} catch (e) {
			error.value = errorMessage(e)
		} finally {
			loading.value = false
		}
	}
	async function create() {
		saving.value = true
		try {
			await run(
				'create',
				() =>
					call('frappe_whatsapp_core.groups.create_group', {
						account_name: account.value,
						...form.value,
					}),
				'Group created.',
			)
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
		selected.value = detail?.data?.[0] || detail || group
		edit.value = {
			subject: selected.value.subject || '',
			description: selected.value.description || '',
		}
	}
	async function saveGroup() {
		await run(
			'save',
			() =>
				call('frappe_whatsapp_core.groups.update_group', {
					account_name: account.value,
					group_id: selected.value.id,
					...edit.value,
				}),
			'Group details updated.',
		)
		await load()
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
		joinRequests.value = result?.data || []
		selectedRequests.value = []
	}
	async function decide(approve) {
		await run(
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
		await loadRequests()
	}
	async function removeParticipants() {
		const participants = participantsToRemove.value.split(/[\s,]+/).filter(Boolean)
		await run(
			'remove',
			() =>
				call('frappe_whatsapp_core.groups.remove_participants', {
					account_name: account.value,
					group_id: selected.value.id,
					participants,
				}),
			'Participants removed.',
		)
		participantsToRemove.value = ''
	}
	async function sendMessage() {
		await run(
			'send',
			() =>
				call('frappe_whatsapp_core.groups.send_group_message', {
					account_name: account.value,
					group_id: selected.value.id,
					message_type: 'text',
					content: { body: messageBody.value },
				}),
			'Message sent.',
		)
		messageBody.value = ''
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
		await run(
			'delete',
			() =>
				call('frappe_whatsapp_core.groups.delete_group', {
					account_name: account.value,
					group_id: selected.value.id,
				}),
			'Group deleted.',
		)
		showManage.value = false
		await load()
	}
	onMounted(() => load(''))
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Meta Groups API</div>
			<h1>WhatsApp Groups</h1>
			<p>Create, moderate and message Meta-hosted business groups without leaving Core.</p>
		</div>
		<Button label="Create group" icon="pi pi-plus" @click="showCreate = true" />
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
		<DataTable :value="rows" :loading="loading" striped-rows responsive-layout="scroll"
			><Column field="subject" header="Group" /><Column
				field="description"
				header="Description"
			/><Column field="total_participant_count" header="Participants" /><Column
				field="join_approval_mode"
				header="Join approval"
			/><Column field="id" header="Meta ID" /><Column header=""
				><template #body="{ data }"
					><Button
						label="Manage"
						size="small"
						outlined
						@click="manage(data)" /></template></Column
			><template #empty
				><div class="empty">No groups returned by this account.</div></template
			></DataTable
		>
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
			</section>
			<section class="manage-card">
				<h3>Participants</h3>
				<label
					>Numbers or participant IDs<Textarea
						v-model="participantsToRemove"
						rows="3"
						placeholder="Comma or line separated" /></label
				><Button
					label="Remove participants"
					severity="danger"
					outlined
					:disabled="!participantsToRemove.trim()"
					:loading="action === 'remove'"
					@click="removeParticipants"
				/>
			</section>
			<section class="manage-card">
				<h3>Message group</h3>
				<label>Message<Textarea v-model="messageBody" rows="3" /></label
				><Button
					label="Send message"
					icon="pi pi-send"
					:disabled="!messageBody.trim()"
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
	.manage-card {
		padding: 16px;
		border: 1px solid var(--wa-border);
		border-radius: 14px;
		align-content: start;
	}
	.manage-card h3 {
		margin: 0;
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
		padding: 48px;
		text-align: center;
		color: #7d8983;
	}
	@media (max-width: 760px) {
		.manage-grid {
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
