<script setup>
	import { computed, onMounted, ref } from 'vue'
	import { useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Skeleton from 'primevue/skeleton'
	import {
		AlertTriangle,
		ArrowRight,
		Bot,
		GitBranch,
		Megaphone,
		MessageCircleMore,
		MessageSquareText,
		Plus,
		Sparkles,
	} from 'lucide-vue-next'
	import MetricCard from '@/components/MetricCard.vue'
	import AsyncState from '@/components/AsyncState.vue'
	import { flowWorkspace } from '@/features/flows/services/flowService'
	import { call, errorMessage } from '@/services/frappe'

	const router = useRouter()
	const loading = ref(true)
	const data = ref({ metrics: {} })
	const meta = ref({ flows: [] })
	const metaError = ref('')
	const loadError = ref('')
	const metrics = computed(() => [
		{
			label: 'Open conversations',
			value: data.value.metrics.open_conversations || 0,
			detail: 'Shared inbox requiring attention',
			icon: MessageCircleMore,
			tone: 'green',
		},
		{
			label: 'Active campaigns',
			value: data.value.metrics.active_campaigns || 0,
			detail: 'Prepared, scheduled or sending',
			icon: Megaphone,
			tone: 'blue',
		},
		{
			label: 'Approved templates',
			value: data.value.metrics.approved_templates || 0,
			detail: 'Available for business-initiated sends',
			icon: MessageSquareText,
			tone: 'purple',
		},
		{
			label: 'Failed messages',
			value: data.value.metrics.failed_messages || 0,
			detail: 'Requires operator review',
			icon: AlertTriangle,
			tone: 'orange',
		},
	])
	const flowLifecycle = computed(() => {
		const counts = meta.value.flows.reduce((result, flow) => {
			result[flow.status] = (result[flow.status] || 0) + 1
			return result
		}, {})
		return [
			{ label: 'Draft', value: counts.DRAFT || 0, tone: 'draft' },
			{ label: 'Published', value: counts.PUBLISHED || 0, tone: 'published' },
			{ label: 'Deprecated', value: counts.DEPRECATED || 0, tone: 'deprecated' },
		]
	})
	const maximum = computed(() => Math.max(...flowLifecycle.value.map((row) => row.value), 1))
	const quickActions = [
		{
			title: 'Create bulk message',
			text: 'Send an approved template to a filtered audience.',
			icon: Megaphone,
			route: 'campaigns',
		},
		{
			title: 'Build a Meta Flow',
			text: 'Create, validate, preview and publish a native WhatsApp Flow.',
			icon: GitBranch,
			route: 'flows',
		},
		{
			title: 'Review AI queue',
			text: 'Approve or correct AI-assisted categorization.',
			icon: Bot,
			route: 'ai-queue',
		},
	]

	onMounted(async () => {
		try {
			data.value = await call('frappe_whatsapp_core.frontend_api.dashboard')
			try {
				meta.value = await flowWorkspace('')
			} catch (error) {
				metaError.value =
					error?.response?.data?.message || 'Meta Flow connection is not configured.'
			}
		} catch (error) {
			loadError.value = errorMessage(error, 'Unable to load WhatsApp operations.')
		} finally {
			loading.value = false
		}
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Operations workspace</div>
			<h1>WhatsApp operations</h1>
		</div>
		<div class="heading-actions">
			<Button
				label="New bulk message"
				severity="secondary"
				outlined
				@click="router.push({ name: 'campaigns' })"
				><template #icon><Megaphone :size="16" /></template></Button
			><Button label="Create Meta Flow" @click="router.push({ name: 'flows' })"
				><template #icon><Plus :size="16" /></template
			></Button>
		</div>
	</div>
	<AsyncState v-if="loadError" :error="loadError" @retry="() => window.location.reload()" />
	<template v-else>
		<section class="metric-grid">
			<template v-if="loading"
				><Skeleton
					v-for="item in 4"
					:key="item"
					height="128px"
					border-radius="17px" /></template
			><MetricCard v-for="metric in metrics" v-else :key="metric.label" v-bind="metric" />
		</section>
		<section class="main-grid">
			<article class="surface-card lifecycle-card">
				<header>
					<div>
						<div class="eyebrow">Meta source of truth</div>
						<h2>Native Flow lifecycle</h2>
					</div>
					<Button
						label="Open Meta Flows"
						text
						size="small"
						@click="router.push({ name: 'flows' })"
					/>
				</header>
				<div v-if="metaError" class="meta-error">{{ metaError }}</div>
				<div v-else class="lifecycle-list">
					<div v-for="row in flowLifecycle" :key="row.label" class="lifecycle-row">
						<div>
							<span>{{ row.label }}</span
							><strong>{{ row.value }}</strong>
						</div>
						<div class="lifecycle-track">
							<i
								:class="row.tone"
								:style="{
									width: `${Math.max((row.value / maximum) * 100, row.value ? 8 : 0)}%`,
								}"
							></i>
						</div>
					</div>
				</div>
			</article>
			<article class="surface-card boundary-card">
				<header>
					<div>
						<div class="eyebrow">Architecture boundary</div>
						<h2>Service ownership</h2>
					</div>
					<Sparkles :size="19" />
				</header>
				<div class="health-row">
					<span class="status-dot"></span>
					<div>
						<strong>WhatsApp Flows</strong><small>Hosted and validated by Meta</small>
					</div>
					<em>Meta</em>
				</div>
				<div class="health-row neutral">
					<span class="status-dot"></span>
					<div>
						<strong>Message relay</strong
						><small>Durable batches through JetStream</small>
					</div>
					<em>Integration</em>
				</div>
				<div class="health-row neutral">
					<span class="status-dot"></span>
					<div>
						<strong>Inbox and teams</strong
						><small>Company access and operations</small>
					</div>
					<em>Core</em>
				</div>
				<Button
					label="Open audit & health"
					text
					fluid
					@click="router.push({ name: 'health' })"
					><template #icon><ArrowRight :size="15" /></template
				></Button>
			</article>
		</section>
		<section>
			<div class="section-title">
				<div>
					<div class="eyebrow">Start here</div>
					<h2>Quick actions</h2>
				</div>
			</div>
			<div class="quick-grid">
				<RouterLink
					v-for="action in quickActions"
					:key="action.title"
					:to="{ name: action.route }"
					class="surface-card quick-card"
					><div class="quick-icon"><component :is="action.icon" :size="20" /></div>
					<div>
						<strong>{{ action.title }}</strong>
					</div>
					<ArrowRight :size="17"
				/></RouterLink>
			</div>
		</section>
	</template>
</template>

<style scoped>
	.heading-actions {
		display: flex;
		gap: 10px;
	}
	.metric-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 14px;
		margin-bottom: 18px;
	}
	.main-grid {
		display: grid;
		grid-template-columns: 1.65fr 0.75fr;
		gap: 18px;
		margin-bottom: 28px;
	}
	.lifecycle-card,
	.boundary-card {
		padding: 20px 22px;
	}
	.lifecycle-card header,
	.boundary-card header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.lifecycle-card h2,
	.boundary-card h2,
	.section-title h2 {
		margin: 5px 0 0;
		font-size: 16px;
	}
	.lifecycle-list {
		display: grid;
		gap: 19px;
		padding: 24px 2px 8px;
	}
	.lifecycle-row > div:first-child {
		display: flex;
		justify-content: space-between;
		margin-bottom: 8px;
		font-size: 11px;
	}
	.lifecycle-track {
		height: 9px;
		overflow: hidden;
		border-radius: 20px;
		background: #edf2ef;
	}
	.lifecycle-track i {
		display: block;
		height: 100%;
		border-radius: inherit;
	}
	.draft {
		background: #93a49c;
	}
	.published {
		background: #1caf7d;
	}
	.deprecated {
		background: #cb625a;
	}
	.meta-error {
		margin-top: 22px;
		padding: 14px;
		border-radius: 10px;
		color: var(--wa-warning);
		background: var(--wa-warning-soft);
		font-size: 12px;
	}
	.health-row {
		display: grid;
		grid-template-columns: 12px 1fr auto;
		align-items: center;
		gap: 10px;
		padding: 16px 0;
		border-bottom: 1px solid var(--wa-border-soft);
	}
	.health-row.neutral .status-dot {
		background: #9caaa3;
		box-shadow: none;
	}
	.health-row strong,
	.health-row small {
		display: block;
	}
	.health-row strong {
		font-size: 11px;
	}
	.health-row small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.health-row em {
		color: var(--wa-muted);
		font-size: 12px;
		font-style: normal;
	}
	.boundary-card > .p-button {
		margin-top: 13px;
	}
	.section-title {
		margin-bottom: 13px;
	}
	.quick-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 14px;
	}
	.quick-card {
		display: grid;
		grid-template-columns: 43px 1fr 20px;
		gap: 13px;
		align-items: center;
		padding: 18px;
		transition: 0.18s;
	}
	.quick-card:hover {
		transform: translateY(-2px);
		box-shadow: 0 12px 30px #0b3d2d12;
	}
	.quick-icon {
		display: grid;
		place-items: center;
		width: 43px;
		height: 43px;
		border-radius: 13px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}
	.quick-card strong {
		font-size: 12px;
	}
	.quick-card p {
		margin: 5px 0 0;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.5;
	}
	@media (max-width: 1100px) {
		.metric-grid {
			grid-template-columns: repeat(2, 1fr);
		}
		.main-grid {
			grid-template-columns: 1fr;
		}
		.quick-grid {
			grid-template-columns: 1fr;
		}
	}
	@media (max-width: 650px) {
		.metric-grid {
			grid-template-columns: 1fr;
		}
		.heading-actions {
			flex-wrap: wrap;
		}
	}
</style>
