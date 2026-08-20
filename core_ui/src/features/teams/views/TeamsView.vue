<script setup>
	import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
	import Button from 'primevue/button'
	import AppDialog from '@/components/AppDialog.vue'
	import InputText from 'primevue/inputtext'
	import Message from 'primevue/message'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import ToggleSwitch from 'primevue/toggleswitch'
	import Tag from 'primevue/tag'
	import {
		Building2,
		Headphones,
		ImagePlus,
		MessageCircleMore,
		Plus,
		Store,
		Trash2,
		UsersRound,
	} from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'
	import AsyncState from '@/components/AsyncState.vue'
	import TeamContactTable from '@/features/teams/components/TeamContactTable.vue'
	import TeamMemberTable from '@/features/teams/components/TeamMemberTable.vue'
	import { call, errorMessage, uploadFile } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'
	import { focusDialogControl } from '@/utils/focus'

	const toast = useToast()
	const session = useSessionStore()
	const teams = ref([])
	const loading = ref(false)
	const saving = ref(false)
	const loadError = ref('')
	const submitError = ref('')
	const attempted = ref(false)
	const visible = ref(false)
	const editingTeam = ref('')
	const dialogRef = ref(null)
	const avatarUploading = ref(false)
	const avatarChanged = ref(false)
	const avatarPreview = ref('')
	const form = reactive({
		team_name: '',
		icon: 'users-round',
		avatar: '',
		description: '',
		enabled: true,
	})
	const iconOptions = [
		{ label: 'People', value: 'users-round', component: UsersRound },
		{ label: 'Customers', value: 'building-2', component: Building2 },
		{ label: 'Retailers', value: 'store', component: Store },
		{ label: 'Support', value: 'headphones', component: Headphones },
		{ label: 'Conversations', value: 'message-circle-more', component: MessageCircleMore },
	]
	const iconComponents = Object.fromEntries(
		iconOptions.map((option) => [option.value, option.component]),
	)
	const canManage = computed(() => Boolean(session.boot?.can_manage))
	let unsubscribe = () => {}
	let refreshTimer = null
	let loadSequence = 0
	function teamIcon(icon) {
		return iconComponents[icon] || UsersRound
	}

	async function load({ silent = false } = {}) {
		const request = ++loadSequence
		if (!silent) loading.value = true
		loadError.value = ''
		try {
			const workspace = await call('frappe_whatsapp_core.workspace_api.list_teams')
			if (request !== loadSequence) return
			teams.value = workspace || []
		} catch (error) {
			if (request === loadSequence)
				loadError.value = errorMessage(error, 'Unable to load teams.')
		} finally {
			if (!silent && request === loadSequence) loading.value = false
		}
	}
	function refreshFromRealtime() {
		window.clearTimeout(refreshTimer)
		refreshTimer = window.setTimeout(() => load({ silent: true }), 180)
	}

	function open(team = null) {
		revokeAvatarPreview()
		editingTeam.value = team?.name || ''
		form.team_name = team?.team_name || ''
		form.icon = team?.icon || 'users-round'
		form.avatar = ''
		avatarPreview.value = team?.avatar_url || ''
		avatarChanged.value = false
		form.description = team?.description || ''
		form.enabled = team ? Boolean(team.enabled) : true
		attempted.value = false
		submitError.value = ''
		visible.value = true
	}

	function revokeAvatarPreview() {
		if (avatarPreview.value?.startsWith('blob:')) URL.revokeObjectURL(avatarPreview.value)
		avatarPreview.value = ''
	}

	async function selectAvatar(event) {
		const file = event.target.files?.[0]
		if (!file) return
		avatarUploading.value = true
		try {
			const stored = await uploadFile(file, true)
			revokeAvatarPreview()
			form.avatar = stored.file_url
			avatarPreview.value = URL.createObjectURL(file)
			avatarChanged.value = true
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Image upload failed',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			avatarUploading.value = false
			event.target.value = ''
		}
	}

	function removeAvatar() {
		revokeAvatarPreview()
		form.avatar = ''
		avatarChanged.value = true
	}

	async function save() {
		attempted.value = true
		submitError.value = ''
		if (!form.team_name.trim()) return
		saving.value = true
		try {
			const payload = {
				team_name: form.team_name,
				icon: form.icon,
				description: form.description,
				enabled: form.enabled ? 1 : 0,
			}
			if (avatarChanged.value) payload.avatar = form.avatar
			const saved = await call('frappe_whatsapp_core.workspace_api.upsert_team', payload)
			editingTeam.value = saved.name
			visible.value = false
			await load()
			toast.add({ severity: 'success', summary: 'Team saved', life: 2500 })
		} catch (error) {
			submitError.value = errorMessage(error, 'Unable to save this team.')
			toast.add({
				severity: 'error',
				summary: 'Could not save team',
				detail: submitError.value,
				life: 4500,
			})
		} finally {
			saving.value = false
		}
	}

	onMounted(async () => {
		await load()
		unsubscribe = subscribe(session.boot?.site, 'whatsapp_core_team', refreshFromRealtime)
	})
	onUnmounted(() => {
		window.clearTimeout(refreshTimer)
		revokeAvatarPreview()
		unsubscribe()
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Ownership and routing</div>
			<h1>Teams</h1>
		</div>
		<Button v-if="canManage" label="Create team" @click="open()">
			<template #icon><Plus :size="16" /></template>
		</Button>
	</div>
	<AsyncState
		:loading="loading"
		:error="loadError"
		:empty="!teams.length"
		loading-label="Loading teams…"
		empty-title="No teams yet"
		empty-message="Create a team to route shared conversations to the right people."
		@retry="load"
	/>
	<section v-if="!loading && !loadError && teams.length" class="team-grid">
		<article v-for="team in teams" :key="team.name" class="surface-card team-card">
			<header>
				<span class="team-icon">
					<img
						v-if="team.avatar_url"
						:src="team.avatar_url"
						:alt="`${team.team_name} image`"
					/>
					<component v-else :is="teamIcon(team.icon)" :size="20" />
				</span>
				<Tag
					:value="team.enabled ? 'Enabled' : 'Disabled'"
					:severity="team.enabled ? 'success' : 'secondary'"
					rounded
				/>
			</header>
			<h2>{{ team.team_name }}</h2>
			<p>{{ team.description || 'No description' }}</p>
			<div class="members">
				<strong>{{ team.member_count || 0 }} members</strong>
				<small>Membership is assigned manually by a WhatsApp Manager.</small>
			</div>
			<div class="contact-count">
				<strong>{{ team.contact_count || 0 }}</strong>
				<span>{{ team.contact_count === 1 ? 'team contact' : 'team contacts' }}</span>
			</div>
			<footer>
				<Button
					v-if="canManage"
					label="Manage team"
					outlined
					size="small"
					@click="open(team)"
				/>
			</footer>
		</article>
	</section>
	<AppDialog
		ref="dialogRef"
		v-model:visible="visible"
		modal
		header="WhatsApp team"
		:style="{ width: '760px', maxWidth: '94vw' }"
		@show="focusDialogControl(dialogRef, '#team-name')"
	>
		<Message v-if="submitError" severity="error" :closable="false">{{ submitError }}</Message>
		<label for="team-name">Team name <span>*</span></label>
		<InputText
			id="team-name"
			v-model="form.team_name"
			fluid
			:invalid="attempted && !form.team_name.trim()"
			@keyup.enter="save"
		/>
		<small v-if="attempted && !form.team_name.trim()" class="field-error"
			>Enter a team name.</small
		>
		<label for="team-icon">Icon</label>
		<Select
			input-id="team-icon"
			v-model="form.icon"
			:options="iconOptions"
			option-label="label"
			option-value="value"
			fluid
		>
			<template #value="slotProps">
				<span class="icon-option">
					<component :is="teamIcon(slotProps.value)" :size="16" />
					{{ iconOptions.find((option) => option.value === slotProps.value)?.label }}
				</span>
			</template>
			<template #option="slotProps">
				<span class="icon-option">
					<component :is="slotProps.option.component" :size="16" />
					{{ slotProps.option.label }}
				</span>
			</template>
		</Select>
		<label>Custom image</label>
		<div class="avatar-editor">
			<span class="team-icon avatar-preview">
				<img v-if="avatarPreview" :src="avatarPreview" alt="Team image preview" />
				<component v-else :is="teamIcon(form.icon)" :size="20" />
			</span>
			<label for="team-avatar" class="avatar-upload">
				<ImagePlus :size="16" />
				{{ avatarUploading ? 'Uploading…' : 'Upload image' }}
			</label>
			<input
				id="team-avatar"
				type="file"
				accept="image/png,image/jpeg,image/webp,image/gif"
				:disabled="avatarUploading"
				@change="selectAvatar"
			/>
			<Button
				v-if="avatarPreview"
				text
				severity="danger"
				label="Remove"
				@click="removeAvatar"
			>
				<template #icon><Trash2 :size="15" /></template>
			</Button>
		</div>
		<small class="field-help"
			>PNG, JPEG, WebP or GIF, up to 5 MB. The icon remains the fallback.</small
		>
		<label for="team-description">Description</label
		><Textarea id="team-description" v-model="form.description" rows="3" fluid />
		<div v-if="editingTeam" class="assignment-sections">
			<TeamMemberTable :team="editingTeam" @changed="load({ silent: true })" />
			<TeamContactTable :team="editingTeam" @changed="load({ silent: true })" />
		</div>
		<small v-else class="field-help"
			>Save this team, then reopen it to assign members and contacts.</small
		>
		<small class="field-help">
			Team contacts are visible only to users sharing an enabled team. A user with no team
			sees only contacts that also have no enabled team.
		</small>
		<div class="enabled">
			<ToggleSwitch input-id="team-enabled" v-model="form.enabled" />
			<label for="team-enabled">Team enabled</label>
		</div>
		<template #footer>
			<Button label="Cancel" text @click="visible = false" />
			<Button
				label="Save team"
				:loading="saving"
				:disabled="!form.team_name.trim()"
				@click="save"
			/>
		</template>
	</AppDialog>
</template>

<style scoped>
	.team-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
		gap: 18px;
	}
	:deep(.p-message) {
		margin: 0 0 16px;
	}
	label span,
	.field-error {
		color: var(--wa-danger);
	}
	.field-error {
		display: block;
		margin: -8px 0 12px;
		font-size: 12px;
	}
	.team-card {
		padding: 20px;
		display: flex;
		flex-direction: column;
	}
	.team-card header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.team-icon {
		width: 42px;
		height: 42px;
		display: grid;
		place-items: center;
		border-radius: 12px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}
	.team-icon img {
		width: 100%;
		height: 100%;
		border-radius: inherit;
		object-fit: cover;
	}
	.avatar-editor {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.avatar-editor > input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
		pointer-events: none;
	}
	.avatar-upload {
		min-height: 38px;
		padding: 8px 11px;
		display: inline-flex;
		align-items: center;
		gap: 7px;
		margin: 0;
		border: 1px solid var(--wa-border);
		border-radius: 9px;
		background: var(--wa-surface);
		cursor: pointer;
	}
	.team-card h2 {
		margin: 18px 0 6px;
		font-size: 18px;
		letter-spacing: -0.015em;
	}
	.team-card > p {
		min-height: 42px;
		margin: 0 0 18px;
		color: var(--wa-muted);
		font-size: 13px;
		line-height: 1.55;
	}
	.members {
		padding: 14px;
		margin-bottom: 16px;
		border-radius: 11px;
		background: var(--wa-surface-muted);
	}
	.members strong {
		display: block;
		margin-bottom: 10px;
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}
	.member-list {
		display: flex;
		flex-wrap: wrap;
		gap: 7px;
	}
	.member-list span {
		max-width: 100%;
		padding: 5px 9px 5px 5px;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		border: 1px solid var(--wa-border);
		border-radius: 999px;
		background: var(--wa-surface);
		color: var(--wa-text);
		font-size: 12px;
		overflow-wrap: anywhere;
	}
	.member-list i {
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		flex: 0 0 22px;
		border-radius: 50%;
		background: var(--wa-mint);
		color: var(--wa-primary);
		font-size: 12px;
		font-style: normal;
		font-weight: 800;
	}
	.member-list small {
		align-self: center;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.contact-count {
		display: flex;
		align-items: baseline;
		gap: 6px;
		margin: -6px 0 16px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.category-summary {
		display: grid;
		gap: 9px;
		padding: 14px;
		margin-bottom: 16px;
		border: 1px solid var(--wa-border);
		border-radius: 11px;
		background: var(--wa-surface);
	}
	.category-summary > div:first-child {
		display: flex;
		align-items: baseline;
		gap: 6px;
	}
	.category-summary > div:first-child strong {
		font-size: 18px;
	}
	.category-summary > div:first-child span,
	.category-summary > small,
	.category-list small {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.category-list {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.category-list span {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 4px 8px;
		border-radius: 999px;
		background: var(--wa-mint);
		color: var(--wa-primary);
		font-size: 11px;
	}
	.contact-count strong {
		color: var(--wa-text);
		font-size: 15px;
	}
	.field-help {
		display: block;
		margin-top: 6px;
		color: var(--wa-muted);
		font-size: 11px;
		line-height: 1.45;
	}
	.assignment-sections {
		display: grid;
		gap: 14px;
		margin-top: 18px;
	}
	.icon-option {
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}
	.team-card footer {
		margin-top: auto;
	}
	.empty {
		min-height: 270px;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: var(--wa-muted);
		font-size: 13px;
		text-align: center;
	}
	.empty strong {
		color: var(--wa-text);
		font-size: 16px;
	}
	label {
		display: block;
		margin: 15px 0 6px;
		font-size: 12px;
		font-weight: 700;
	}
	.enabled {
		margin-top: 16px;
		display: flex;
		align-items: center;
		gap: 9px;
		font-size: 12px;
	}
	.enabled label {
		margin: 0;
	}
	@media (max-width: 1000px) {
		.team-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}
	@media (max-width: 650px) {
		.team-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
