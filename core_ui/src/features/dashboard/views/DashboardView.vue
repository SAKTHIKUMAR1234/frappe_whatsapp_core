<script setup>
	import { computed, onMounted, ref } from 'vue'
	import { useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Skeleton from 'primevue/skeleton'
	import {
		Activity,
		AlertTriangle,
		ArrowRight,
		Bot,
		GitBranch,
		Layers3,
		Megaphone,
		Plus,
		Sparkles,
	} from 'lucide-vue-next'

	import MetricCard from '@/components/MetricCard.vue'
	import { call } from '@/services/frappe'

	const router = useRouter()
	const loading = ref(true)
	const data = ref({
		metrics: {},
		lifecycle: {},
		recent_flows: [],
	})

	const metrics = computed(() => [
		{
			label: 'Configured flows',
			value: data.value.metrics.configured_flows || 0,
			detail: 'Reusable company automations',
			icon: Layers3,
			tone: 'green',
		},
		{
			label: 'Published flows',
			value: data.value.metrics.active_flows || 0,
			detail: 'Enabled immutable versions',
			icon: GitBranch,
			tone: 'blue',
		},
		{
			label: 'Active journeys',
			value: data.value.metrics.running_instances || 0,
			detail: 'Running or waiting for input',
			icon: Activity,
			tone: 'purple',
		},
		{
			label: 'Failed steps',
			value: data.value.metrics.failed_steps || 0,
			detail: 'Requires operator review',
			icon: AlertTriangle,
			tone: 'orange',
		},
	])

	const lifecycle = computed(() => {
		const rows = [
			{ label: 'Draft flows', value: data.value.lifecycle.draft || 0, tone: 'draft' },
			{
				label: 'Published flows',
				value: data.value.lifecycle.published || 0,
				tone: 'published',
			},
			{
				label: 'Waiting journeys',
				value: data.value.lifecycle.waiting || 0,
				tone: 'waiting',
			},
			{
				label: 'Completed journeys',
				value: data.value.lifecycle.completed || 0,
				tone: 'completed',
			},
		]
		const maximum = Math.max(...rows.map((row) => row.value), 1)
		return rows.map((row) => ({
			...row,
			width: `${Math.max((row.value / maximum) * 100, row.value ? 8 : 0)}%`,
		}))
	})

	const quickActions = [
		{
			title: 'Create bulk message',
			text: 'Send an approved template to a filtered audience.',
			icon: Megaphone,
			route: 'campaigns',
		},
		{
			title: 'Build a flow',
			text: 'Drag questions, branches and registered actions.',
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
		} finally {
			loading.value = false
		}
	})
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Company workspace</div>
			<h1>WhatsApp operations</h1>
			<p>Configure reusable messaging capabilities for this Frappe site.</p>
		</div>
		<div class="heading-actions">
			<Button
				label="New bulk message"
				severity="secondary"
				outlined
				@click="router.push({ name: 'campaigns' })"
			>
				<template #icon><Megaphone :size="16" /></template>
			</Button>
			<Button label="Create flow" @click="router.push({ name: 'flows' })">
				<template #icon><Plus :size="16" /></template>
			</Button>
		</div>
	</div>

	<section class="metric-grid">
		<template v-if="loading">
			<Skeleton v-for="item in 4" :key="item" height="128px" border-radius="17px" />
		</template>
		<MetricCard v-for="metric in metrics" v-else :key="metric.label" v-bind="metric" />
	</section>

	<section class="main-grid">
		<article class="surface-card lifecycle-card">
			<header>
				<div>
					<div class="eyebrow">Live site data</div>
					<h2>Flow lifecycle</h2>
				</div>
				<Button
					label="Open Flow Builder"
					text
					size="small"
					@click="router.push({ name: 'flows' })"
				/>
			</header>

			<div class="lifecycle-list">
				<div v-for="row in lifecycle" :key="row.label" class="lifecycle-row">
					<div>
						<span>{{ row.label }}</span>
						<strong>{{ row.value }}</strong>
					</div>
					<div class="lifecycle-track">
						<i :class="row.tone" :style="{ width: row.width }"></i>
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
					<strong>Flow engine</strong>
					<small>Owned by WhatsApp Core</small>
				</div>
				<em>Local</em>
			</div>
			<div class="health-row neutral">
				<span class="status-dot"></span>
				<div>
					<strong>Message relay</strong>
					<small>Telemetry comes from Integration</small>
				</div>
				<em>External</em>
			</div>
			<div class="health-row neutral">
				<span class="status-dot"></span>
				<div>
					<strong>Meta templates</strong>
					<small>Managed only in Integration Desk</small>
				</div>
				<em>Read-only</em>
			</div>
			<Button
				label="Open audit & health"
				text
				fluid
				@click="router.push({ name: 'health' })"
			>
				<template #icon><ArrowRight :size="15" /></template>
			</Button>
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
			>
				<div class="quick-icon"><component :is="action.icon" :size="20" /></div>
				<div>
					<strong>{{ action.title }}</strong>
					<p>{{ action.text }}</p>
				</div>
				<ArrowRight :size="17" />
			</RouterLink>
		</div>
	</section>
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
		transition: width 0.25s ease;
	}

	.lifecycle-track .draft {
		background: #93a49c;
	}

	.lifecycle-track .published {
		background: #1caf7d;
	}

	.lifecycle-track .waiting {
		background: #7d62d9;
	}

	.lifecycle-track .completed {
		background: #3a78d0;
	}

	.health-row {
		display: grid;
		grid-template-columns: 12px 1fr auto;
		align-items: center;
		gap: 10px;
		padding: 16px 0;
		border-bottom: 1px solid #edf1ef;
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
		color: #829088;
		font-size: 9px;
	}

	.health-row em {
		color: #6f7d76;
		font-size: 9px;
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
		color: #08745a;
		background: #e2f7ee;
	}

	.quick-card strong {
		font-size: 12px;
	}

	.quick-card p {
		margin: 5px 0 0;
		color: #7c8983;
		font-size: 9px;
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

	@media (max-width: 600px) {
		.metric-grid {
			grid-template-columns: 1fr;
		}

		.heading-actions {
			width: 100%;
		}
	}
</style>
