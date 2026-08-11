<script setup>
	import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
	import Button from 'primevue/button'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Message from 'primevue/message'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import ToggleSwitch from 'primevue/toggleswitch'
	import Tag from 'primevue/tag'
	import {
		Building2,
		Headphones,
		MessageCircleMore,
		Plus,
		Store,
		UsersRound,
	} from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'
	import AsyncState from '@/components/AsyncState.vue'
	import ContactMultiSelect from '@/features/contacts/components/ContactMultiSelect.vue'
	import UserMultiSelect from '@/features/teams/components/UserMultiSelect.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'
	import { focusDialogControl } from '@/utils/focus'

	const toast = useToast()
	const session = useSessionStore()
	const teams = ref([])
	const userOptions = ref([])
	const contactOptions = ref([])
	const loading = ref(false)
	const saving = ref(false)
	const loadError = ref('')
	const submitError = ref('')
	const attempted = ref(false)
	const visible = ref(false)
	const dialogRef = ref(null)
	const form = reactive({
		team_name: '',
		icon: 'users-round',
		description: '',
		enabled: true,
		members: [],
		contacts: [],
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
	const userByName = computed(() =>
		Object.fromEntries(userOptions.value.map((user) => [user.name, user])),
	)

	function memberLabel(user) {
		return userByName.value[user]?.full_name || user
	}

	function teamIcon(icon) {
		return iconComponents[icon] || UsersRound
	}

	async function load({ silent = false } = {}) {
		const request = ++loadSequence
		if (!silent) loading.value = true
		loadError.value = ''
		try {
			const workspace = await call('frappe_whatsapp_core.workspace_api.team_workspace')
			if (request !== loadSequence) return
			teams.value = workspace.teams || []
			userOptions.value = workspace.users || []
			contactOptions.value = workspace.contacts || []
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
		form.team_name = team?.team_name || ''
		form.icon = team?.icon || 'users-round'
		form.description = team?.description || ''
		form.enabled = team ? Boolean(team.enabled) : true
		form.members = (team?.members || []).map((member) => member.user)
		form.contacts = (team?.contacts || []).map((contact) => contact.identity)
		attempted.value = false
		submitError.value = ''
		visible.value = true
	}

	async function save() {
		attempted.value = true
		submitError.value = ''
		if (!form.team_name.trim()) return
		saving.value = true
		try {
			await call('frappe_whatsapp_core.workspace_api.upsert_team', {
				team_name: form.team_name,
				icon: form.icon,
				description: form.description,
				enabled: form.enabled ? 1 : 0,
				members: form.members.map((user) => ({ user, team_role: 'Agent', enabled: 1 })),
				contacts: form.contacts.map((identity) => ({ identity, enabled: 1 })),
			})
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
		unsubscribe()
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Ownership and routing</div>
			<h1>Teams</h1>
			<p>Group Frappe users so conversations can be assigned and handled together.</p>
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
				<span class="team-icon"><component :is="teamIcon(team.icon)" :size="20" /></span>
				<Tag
					:value="team.enabled ? 'Enabled' : 'Disabled'"
					:severity="team.enabled ? 'success' : 'secondary'"
					rounded
				/>
			</header>
			<h2>{{ team.team_name }}</h2>
			<p>{{ team.description || 'No description' }}</p>
			<div class="members">
				<strong
					>{{ team.members.length }}
					{{ team.members.length === 1 ? 'member' : 'members' }}</strong
				>
				<div class="member-list">
					<span v-for="member in team.members.slice(0, 5)" :key="member.user">
						<i>{{ memberLabel(member.user).slice(0, 1).toUpperCase() }}</i>
						{{ memberLabel(member.user) }}
					</span>
					<small v-if="team.members.length > 5"
						>+{{ team.members.length - 5 }} more</small
					>
				</div>
			</div>
			<div class="contact-count">
				<strong>{{ team.contacts.length }}</strong>
				<span>{{
					team.contacts.length === 1 ? 'categorized contact' : 'categorized contacts'
				}}</span>
			</div>
			<div class="category-summary">
				<div>
					<strong>{{ team.categorized_messages || 0 }}</strong>
					<span>categorized messages</span>
				</div>
				<div v-if="team.categories?.length" class="category-list">
					<span v-for="category in team.categories.slice(0, 5)" :key="category.category">
						{{ category.category }} <strong>{{ category.count }}</strong>
					</span>
					<small v-if="team.categories.length > 5">
						+{{ team.categories.length - 5 }} more categories
					</small>
				</div>
				<small v-else>No categorized messages yet.</small>
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
	<Dialog
		ref="dialogRef"
		v-model:visible="visible"
		modal
		header="WhatsApp team"
		:style="{ width: '440px', maxWidth: '94vw' }"
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
		<label for="team-description">Description</label
		><Textarea id="team-description" v-model="form.description" rows="3" fluid />
		<label id="team-members-label">Members</label>
		<UserMultiSelect
			v-model="form.members"
			:options="userOptions"
			aria-labelledby="team-members-label"
		/>
		<label id="team-contacts-label">Contacts</label>
		<ContactMultiSelect
			v-model="form.contacts"
			:options="contactOptions"
			placeholder="Search and assign contacts"
			aria-labelledby="team-contacts-label"
		/>
		<small class="field-help">
			Categorized contacts are visible only to members of at least one assigned team.
			Uncategorized contacts remain visible to every WhatsApp User.
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
	</Dialog>
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
