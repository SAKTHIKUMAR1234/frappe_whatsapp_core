<script setup>
	import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
	import { useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Skeleton from 'primevue/skeleton'
	import {
		ArrowRight,
		CheckCheck,
		Clock3,
		Inbox,
		MessageCircleMore,
		MessagesSquare,
		UsersRound,
	} from 'lucide-vue-next'
	import MetricCard from '@/components/MetricCard.vue'
	import AsyncState from '@/components/AsyncState.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'

	const router = useRouter()
	const session = useSessionStore()
	const loading = ref(true)
	const refreshing = ref(false)
	const data = ref({ metrics: {}, teams: [] })
	const loadError = ref('')
	let unsubscribe = () => {}

	const metrics = computed(() => [
		{
			label: 'Open conversations',
			value: data.value.metrics.open_conversations || 0,
			detail: 'Customers currently requiring attention',
			icon: MessageCircleMore,
			tone: 'green',
		},
		{
			label: 'Unread conversations',
			value: data.value.metrics.unread_conversations || 0,
			detail: 'Unread for your own account',
			icon: MessagesSquare,
			tone: 'blue',
		},
		{
			label: 'Unassigned queue',
			value: data.value.metrics.unassigned_conversations || 0,
			detail: 'Contacts waiting for ownership',
			icon: Inbox,
			tone: 'orange',
		},
		{
			label: 'Active today',
			value: data.value.metrics.active_today || 0,
			detail: 'Customer conversations touched today',
			icon: Clock3,
			tone: 'purple',
		},
	])

	async function load({ silent = false } = {}) {
		if (silent) refreshing.value = true
		else loading.value = true
		loadError.value = ''
		try {
			data.value = await call('frappe_whatsapp_core.frontend_api.dashboard')
		} catch (error) {
			loadError.value = errorMessage(error, 'Unable to load customer operations.')
		} finally {
			loading.value = false
			refreshing.value = false
		}
	}

	function openTeam(team) {
		router.push({ name: 'inbox', query: { team: team.name } })
	}

	onMounted(async () => {
		await load()
		const site = session.boot?.site
		unsubscribe = subscribe(site, 'whatsapp_core_batch_committed', () =>
			load({ silent: true }),
		)
	})
	onBeforeUnmount(() => unsubscribe())
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Customer operations</div>
			<h1>Team overview</h1>
			<p>Workload, ownership and customer activity within your access scope.</p>
		</div>
		<div class="heading-actions">
			<Button label="Open shared inbox" @click="router.push({ name: 'inbox' })">
				<template #icon><ArrowRight :size="16" /></template>
			</Button>
		</div>
	</div>

	<AsyncState v-if="loadError" :error="loadError" @retry="load" />
	<template v-else>
		<section class="metric-grid">
			<template v-if="loading">
				<Skeleton v-for="item in 4" :key="item" height="128px" border-radius="17px" />
			</template>
			<MetricCard v-for="metric in metrics" v-else :key="metric.label" v-bind="metric" />
		</section>

		<section class="team-section">
			<header class="section-heading">
				<div>
					<div class="eyebrow">Team workload</div>
					<h2>Your customer queues</h2>
				</div>
				<span v-if="refreshing" class="refreshing">Updating live…</span>
			</header>
			<div v-if="loading" class="team-grid">
				<Skeleton v-for="item in 3" :key="item" height="210px" border-radius="17px" />
			</div>
			<div v-else-if="data.teams?.length" class="team-grid">
				<article
					v-for="team in data.teams"
					:key="team.name"
					class="surface-card team-card"
					role="button"
					tabindex="0"
					@click="openTeam(team)"
					@keydown.enter="openTeam(team)"
				>
					<header>
						<span class="team-avatar">
							<img v-if="team.avatar_url" :src="team.avatar_url" alt="" />
							<UsersRound v-else :size="20" />
						</span>
						<div>
							<strong>{{ team.team_name }}</strong
							><small>{{ team.member_count }} members</small>
						</div>
						<ArrowRight :size="17" />
					</header>
					<div class="team-stats">
						<div>
							<span>Customers</span><strong>{{ team.contact_count }}</strong>
						</div>
						<div>
							<span>Open</span><strong>{{ team.open_conversations }}</strong>
						</div>
						<div :class="{ attention: team.unread_conversations }">
							<span>Unread for you</span
							><strong>{{ team.unread_conversations }}</strong>
						</div>
					</div>
					<footer>
						<CheckCheck :size="14" />
						<span>{{ team.conversation_count }} total conversations</span>
					</footer>
				</article>
			</div>
			<div v-else class="empty-teams surface-card">
				<UsersRound :size="28" />
				<strong>No team queues are visible</strong>
				<span>Unassigned conversations remain available from the shared inbox.</span>
			</div>
		</section>
	</template>
</template>

<style scoped>
	.page-heading p {
		margin: 7px 0 0;
		color: var(--wa-muted);
		font-size: 13px;
	}
	.heading-actions {
		display: flex;
		gap: 10px;
	}
	.metric-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 14px;
		margin-bottom: 28px;
	}
	.section-heading {
		display: flex;
		align-items: end;
		justify-content: space-between;
		margin-bottom: 14px;
	}
	.section-heading h2 {
		margin: 5px 0 0;
		font-size: 18px;
	}
	.refreshing {
		color: var(--wa-primary);
		font-size: 11px;
	}
	.team-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 15px;
	}
	.team-card {
		padding: 18px;
		cursor: pointer;
		transition:
			transform 220ms var(--wa-motion-standard),
			border-color 220ms var(--wa-motion-standard),
			box-shadow 220ms var(--wa-motion-standard);
	}
	.team-card:hover,
	.team-card:focus-visible {
		transform: translateY(-2px);
		border-color: color-mix(in srgb, var(--wa-primary) 42%, var(--wa-border));
		box-shadow: 0 17px 36px rgba(5, 18, 28, 0.14);
		outline: none;
	}
	.team-card > header {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 11px;
	}
	.team-card header strong,
	.team-card header small {
		display: block;
	}
	.team-card header small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.team-avatar {
		display: grid;
		place-items: center;
		width: 42px;
		height: 42px;
		border-radius: 13px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		overflow: hidden;
	}
	.team-avatar img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.team-stats {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 8px;
		margin-top: 18px;
	}
	.team-stats > div {
		min-width: 0;
		padding: 11px;
		border-radius: 11px;
		background: var(--wa-surface-muted);
	}
	.team-stats span,
	.team-stats strong {
		display: block;
	}
	.team-stats span {
		color: var(--wa-muted);
		font-size: 10px;
	}
	.team-stats strong {
		margin-top: 5px;
		font-size: 19px;
	}
	.team-stats .attention {
		color: var(--wa-warning);
		background: var(--wa-warning-soft);
	}
	.team-card footer {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 14px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.empty-teams {
		display: grid;
		place-items: center;
		gap: 7px;
		padding: 48px;
		color: var(--wa-muted);
		text-align: center;
	}
	.empty-teams strong {
		color: var(--wa-text);
	}
	@media (max-width: 1120px) {
		.metric-grid {
			grid-template-columns: repeat(2, 1fr);
		}
		.team-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
	@media (max-width: 680px) {
		.page-heading {
			align-items: start;
		}
		.heading-actions {
			width: 100%;
		}
		.heading-actions :deep(.p-button) {
			width: 100%;
		}
		.metric-grid,
		.team-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
