<script setup>
	import { onMounted, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import Message from 'primevue/message'
	import { Plus, Trash2 } from 'lucide-vue-next'
	import LinkField from '@/components/form/LinkField.vue'
	import { call, errorMessage } from '@/services/frappe'

	const props = defineProps({ team: { type: String, required: true } })
	const emit = defineEmits(['changed'])
	const rows = ref([])
	const selectedUser = ref('')
	const loading = ref(false)
	const saving = ref(false)
	const hasMore = ref(false)
	const failure = ref('')

	function present(users) {
		return (users || []).map((user) => ({
			...user,
			label:
				user.full_name && user.full_name !== user.name
					? `${user.full_name} (${user.name})`
					: user.name,
			description: user.user_type || '',
		}))
	}

	async function searchUsers(search) {
		return present(
			await call('frappe_whatsapp_core.workspace_api.search_team_users', {
				search,
				limit: 50,
			}),
		)
	}

	async function load({ append = false } = {}) {
		loading.value = true
		failure.value = ''
		try {
			const result = await call('frappe_whatsapp_core.workspace_api.team_member_page', {
				team: props.team,
				limit: 50,
				offset: append ? rows.value.length : 0,
			})
			rows.value = append ? [...rows.value, ...(result.rows || [])] : result.rows || []
			hasMore.value = Boolean(result.has_more)
		} catch (error) {
			failure.value = errorMessage(error, 'Unable to load team members.')
		} finally {
			loading.value = false
		}
	}

	async function add() {
		if (!selectedUser.value) return
		saving.value = true
		failure.value = ''
		try {
			await call('frappe_whatsapp_core.workspace_api.add_team_member', {
				team: props.team,
				user: selectedUser.value,
			})
			selectedUser.value = ''
			await load()
			emit('changed', rows.value.length)
		} catch (error) {
			failure.value = errorMessage(error, 'Unable to add this member.')
		} finally {
			saving.value = false
		}
	}

	async function remove(row) {
		saving.value = true
		failure.value = ''
		try {
			await call('frappe_whatsapp_core.workspace_api.remove_team_member', {
				team: props.team,
				user: row.user,
			})
			rows.value = rows.value.filter((item) => item.user !== row.user)
			emit('changed', rows.value.length)
		} catch (error) {
			failure.value = errorMessage(error, 'Unable to remove this member.')
		} finally {
			saving.value = false
		}
	}

	watch(
		() => props.team,
		() => load(),
	)
	onMounted(() => load())
</script>

<template>
	<section class="assignment-table">
		<header>
			<div>
				<strong>Team members</strong
				><small>Members receive access to this team’s contacts.</small>
			</div>
			<span>{{ rows.length }}{{ hasMore ? '+' : '' }}</span>
		</header>
		<Message v-if="failure" severity="error" :closable="false">{{ failure }}</Message>
		<div class="assignment-add">
			<LinkField
				v-model="selectedUser"
				:options="[]"
				option-label="label"
				option-value="name"
				placeholder="Search an enabled user"
				aria-label="Search an enabled user to add"
				:search="searchUsers"
			/>
			<Button label="Add" :loading="saving" :disabled="!selectedUser" @click="add">
				<template #icon><Plus :size="15" /></template>
			</Button>
		</div>
		<div class="table-scroll">
			<table>
				<thead>
					<tr>
						<th>User</th>
						<th>Type</th>
						<th aria-label="Actions"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="row in rows" :key="row.name">
						<td>
							<strong>{{ row.full_name || row.user }}</strong
							><small v-if="row.full_name">{{ row.user }}</small>
						</td>
						<td>{{ row.user_type || 'User' }}</td>
						<td>
							<Button
								text
								rounded
								severity="danger"
								aria-label="Remove team member"
								:disabled="saving"
								@click="remove(row)"
								><Trash2 :size="15"
							/></Button>
						</td>
					</tr>
					<tr v-if="!loading && !rows.length">
						<td colspan="3" class="empty-row">No members assigned.</td>
					</tr>
				</tbody>
			</table>
		</div>
		<Button
			v-if="hasMore"
			label="Load more members"
			text
			:loading="loading"
			@click="load({ append: true })"
		/>
	</section>
</template>

<style scoped>
	.assignment-table {
		display: grid;
		gap: 10px;
		padding: 14px;
		border: 1px solid var(--wa-border);
		border-radius: 12px;
	}
	.assignment-table header,
	.assignment-add {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}
	.assignment-table header div,
	td:first-child {
		display: grid;
		gap: 2px;
	}
	.assignment-table header small,
	td small {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.assignment-add > :first-child {
		flex: 1 1 auto;
		min-width: 0;
	}
	.table-scroll {
		max-height: 250px;
		overflow: auto;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 12px;
	}
	th,
	td {
		padding: 8px;
		border-bottom: 1px solid var(--wa-border);
		text-align: left;
	}
	th:last-child,
	td:last-child {
		width: 44px;
		text-align: right;
	}
	.empty-row {
		padding: 22px;
		color: var(--wa-muted);
		text-align: center;
	}
	@media (max-width: 560px) {
		.assignment-add {
			align-items: stretch;
			flex-direction: column;
		}
	}
</style>
