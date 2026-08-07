<script setup>
	import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
	import Button from 'primevue/button'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Message from 'primevue/message'
	import MultiSelect from 'primevue/multiselect'
	import Textarea from 'primevue/textarea'
	import ToggleSwitch from 'primevue/toggleswitch'
	import Tag from 'primevue/tag'
	import { Plus, UsersRound } from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'
	import AsyncState from '@/components/AsyncState.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'

	const toast = useToast()
	const session = useSessionStore()
	const teams = ref([])
	const userOptions = ref([])
	const loading = ref(false)
	const saving = ref(false)
	const loadError = ref('')
	const submitError = ref('')
	const attempted = ref(false)
	const visible = ref(false)
	const form = reactive({ team_name: '', description: '', enabled: true, members: [] })
	const canManage = computed(() => Boolean(session.boot?.can_manage))
	let unsubscribe = () => {}
	const userByName = computed(() =>
		Object.fromEntries(userOptions.value.map((user) => [user.name, user])),
	)

	function memberLabel(user) {
		return userByName.value[user]?.full_name || user
	}

	async function load() {
		loading.value = true
		loadError.value = ''
		try {
			const workspace = await call('frappe_whatsapp_core.workspace_api.team_workspace')
			teams.value = workspace.teams || []
			userOptions.value = workspace.users || []
		} catch (error) {
			loadError.value = errorMessage(error, 'Unable to load teams.')
		} finally {
			loading.value = false
		}
	}

	function open(team = null) {
		form.team_name = team?.team_name || ''
		form.description = team?.description || ''
		form.enabled = team ? Boolean(team.enabled) : true
		form.members = (team?.members || []).map((member) => member.user)
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
				description: form.description,
				enabled: form.enabled ? 1 : 0,
				members: form.members.map((user) => ({ user, team_role: 'Agent', enabled: 1 })),
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
		unsubscribe = subscribe(session.boot?.site, 'whatsapp_core_team', load)
	})
	onUnmounted(() => unsubscribe())
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
				<span class="team-icon"><UsersRound :size="20" /></span>
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
		v-model:visible="visible"
		modal
		header="WhatsApp team"
		:style="{ width: '440px', maxWidth: '94vw' }"
	>
		<Message v-if="submitError" severity="error" :closable="false">{{ submitError }}</Message>
		<label for="team-name">Team name <span>*</span></label>
		<InputText
			id="team-name"
			v-model="form.team_name"
			fluid
			:invalid="attempted && !form.team_name.trim()"
			autofocus
			@keyup.enter="save"
		/>
		<small v-if="attempted && !form.team_name.trim()" class="field-error"
			>Enter a team name.</small
		>
		<label>Description</label><Textarea v-model="form.description" rows="3" fluid />
		<label>Members</label>
		<MultiSelect
			v-model="form.members"
			:options="userOptions"
			option-label="label"
			option-value="name"
			filter
			display="chip"
			:show-toggle-all="false"
			:max-selected-labels="4"
			fluid
			placeholder="Search and select Frappe users"
		>
			<template #option="{ option }">
				<div class="user-option">
					<strong>{{ option.full_name || option.name }}</strong>
					<small>{{ option.name }}</small>
				</div>
			</template>
		</MultiSelect>
		<div class="enabled"><ToggleSwitch v-model="form.enabled" /><span>Team enabled</span></div>
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
		color: #087354;
		background: #ddf8eb;
	}
	.team-card h2 {
		margin: 18px 0 6px;
		font-size: 18px;
		letter-spacing: -0.015em;
	}
	.team-card > p {
		min-height: 42px;
		margin: 0 0 18px;
		color: #77857e;
		font-size: 13px;
		line-height: 1.55;
	}
	.members {
		padding: 14px;
		margin-bottom: 16px;
		border-radius: 11px;
		background: #f6f9f7;
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
		border: 1px solid #dfe9e4;
		border-radius: 999px;
		background: white;
		color: #5f6f67;
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
		font-size: 10px;
		font-style: normal;
		font-weight: 800;
	}
	.member-list small {
		align-self: center;
		color: var(--wa-muted);
		font-size: 12px;
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
		color: #829088;
		font-size: 13px;
		text-align: center;
	}
	.empty strong {
		color: #26352e;
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
	.user-option {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.user-option strong,
	.user-option small {
		overflow-wrap: anywhere;
	}
	.user-option small {
		color: var(--wa-muted);
		font-size: 11px;
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
