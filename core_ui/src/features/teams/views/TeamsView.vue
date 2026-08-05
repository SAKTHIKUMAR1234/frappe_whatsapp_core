<script setup>
	import { computed, onMounted, reactive, ref } from 'vue'
	import Button from 'primevue/button'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Textarea from 'primevue/textarea'
	import ToggleSwitch from 'primevue/toggleswitch'
	import Tag from 'primevue/tag'
	import { Plus, UsersRound } from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'
	import { call } from '@/services/frappe'
	import { useSessionStore } from '@/stores/session'

	const toast = useToast()
	const session = useSessionStore()
	const teams = ref([])
	const loading = ref(false)
	const saving = ref(false)
	const visible = ref(false)
	const form = reactive({ team_name: '', description: '', enabled: true, members: '' })
	const canManage = computed(() => Boolean(session.boot?.can_manage))

	async function load() {
		loading.value = true
		try {
			teams.value = await call('frappe_whatsapp_core.workspace_api.list_teams')
		} finally {
			loading.value = false
		}
	}

	function open(team = null) {
		form.team_name = team?.team_name || ''
		form.description = team?.description || ''
		form.enabled = team ? Boolean(team.enabled) : true
		form.members = (team?.members || []).map((member) => member.user).join('\n')
		visible.value = true
	}

	async function save() {
		saving.value = true
		try {
			await call('frappe_whatsapp_core.workspace_api.upsert_team', {
				team_name: form.team_name,
				description: form.description,
				enabled: form.enabled ? 1 : 0,
				members: form.members
					.split('\n')
					.map((user) => user.trim())
					.filter(Boolean)
					.map((user) => ({ user, team_role: 'Agent', enabled: 1 })),
			})
			visible.value = false
			await load()
			toast.add({ severity: 'success', summary: 'Team saved', life: 2500 })
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Could not save team',
				detail: error?.response?.data?.message || error?.message,
				life: 4500,
			})
		} finally {
			saving.value = false
		}
	}

	onMounted(load)
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
	<section class="team-grid">
		<article v-for="team in teams" :key="team.name" class="surface-card team-card">
			<header>
				<span><UsersRound :size="20" /></span>
				<Tag
					:value="team.enabled ? 'Enabled' : 'Disabled'"
					:severity="team.enabled ? 'success' : 'secondary'"
					rounded
				/>
			</header>
			<h2>{{ team.team_name }}</h2>
			<p>{{ team.description || 'No description' }}</p>
			<div class="members">
				<strong>{{ team.members.length }} members</strong>
				<span v-for="member in team.members.slice(0, 4)" :key="member.user">{{
					member.user
				}}</span>
				<small v-if="team.members.length > 4">+{{ team.members.length - 4 }} more</small>
			</div>
			<Button v-if="canManage" label="Edit team" outlined size="small" @click="open(team)" />
		</article>
		<div v-if="!loading && !teams.length" class="surface-card empty">
			<UsersRound :size="32" /><strong>No teams yet</strong
			><span>Create a team to route shared conversations.</span>
		</div>
	</section>
	<Dialog
		v-model:visible="visible"
		modal
		header="WhatsApp team"
		:style="{ width: '440px', maxWidth: '94vw' }"
	>
		<label>Team name</label><InputText v-model="form.team_name" fluid />
		<label>Description</label><Textarea v-model="form.description" rows="3" fluid />
		<label>Members</label>
		<Textarea
			v-model="form.members"
			rows="7"
			fluid
			placeholder="One Frappe user email per line"
		/>
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
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 15px;
	}
	.team-card {
		padding: 18px;
	}
	.team-card header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.team-card header > span {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		border-radius: 12px;
		color: #087354;
		background: #ddf8eb;
	}
	.team-card h2 {
		margin: 17px 0 5px;
		font-size: 16px;
	}
	.team-card > p {
		min-height: 34px;
		margin: 0 0 16px;
		color: #77857e;
		font-size: 10px;
		line-height: 1.6;
	}
	.members {
		min-height: 100px;
		padding: 12px;
		margin-bottom: 15px;
		display: flex;
		flex-direction: column;
		gap: 5px;
		border-radius: 11px;
		background: #f6f9f7;
	}
	.members strong {
		margin-bottom: 3px;
		font-size: 9px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}
	.members span,
	.members small {
		color: #5f6f67;
		font-size: 9px;
	}
	.empty {
		min-height: 270px;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: #829088;
		font-size: 11px;
		text-align: center;
	}
	.empty strong {
		color: #26352e;
		font-size: 14px;
	}
	label {
		display: block;
		margin: 15px 0 6px;
		font-size: 10px;
		font-weight: 700;
	}
	.enabled {
		margin-top: 16px;
		display: flex;
		align-items: center;
		gap: 9px;
		font-size: 10px;
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
