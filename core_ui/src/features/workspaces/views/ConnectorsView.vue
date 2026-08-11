<script setup>
	import { onMounted, ref } from 'vue'
	import Button from 'primevue/button'
	import Column from 'primevue/column'
	import DataTable from 'primevue/datatable'
	import Skeleton from 'primevue/skeleton'
	import Tag from 'primevue/tag'
	import { Bot, Braces, PlugZap, RefreshCw, ShieldCheck } from 'lucide-vue-next'

	import AsyncState from '@/components/AsyncState.vue'
	import { call, errorMessage } from '@/services/frappe'

	const loading = ref(true)
	const loadError = ref('')
	const workspace = ref({
		mcp_tools: [],
		flow_actions: [],
		extension_points: [],
		metrics: {},
	})
	let loadSequence = 0

	async function load() {
		const request = ++loadSequence
		loading.value = true
		loadError.value = ''
		try {
			const loaded = await call('frappe_whatsapp_core.frontend_api.connectors_workspace')
			if (request !== loadSequence) return
			workspace.value = loaded
		} catch (error) {
			if (request === loadSequence)
				loadError.value = errorMessage(error, 'Unable to load connector capabilities.')
		} finally {
			if (request === loadSequence) loading.value = false
		}
	}

	onMounted(load)
</script>

<template>
	<div class="page-heading">
		<div>
			<div class="eyebrow">Typed integration boundary</div>
			<h1>Connectors</h1>
			<p>Inspect the allowlisted actions exposed by Core and the installed company layer.</p>
		</div>
		<Button
			label="Refresh registry"
			outlined
			:loading="loading"
			:disabled="loading"
			@click="load"
		>
			<template #icon><RefreshCw :size="16" /></template>
		</Button>
	</div>
	<AsyncState v-if="loadError" :error="loadError" @retry="load" />
	<template v-else>
		<section class="summary-grid">
			<article class="surface-card">
				<Bot :size="19" />
				<div>
					<small>MCP tools</small><strong>{{ workspace.metrics.mcp_tools || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card">
				<Braces :size="19" />
				<div>
					<small>Flow actions</small
					><strong>{{ workspace.metrics.flow_actions || 0 }}</strong>
				</div>
			</article>
			<article class="surface-card">
				<PlugZap :size="19" />
				<div>
					<small>Configured extensions</small
					><strong>{{ workspace.metrics.configured_extensions || 0 }}</strong>
				</div>
			</article>
		</section>

		<div class="endpoint-card">
			<ShieldCheck :size="18" />
			<div>
				<strong>Authenticated MCP endpoint</strong>
				<code>{{ workspace.mcp_endpoint }}</code>
			</div>
			<span>Stateless · audited · no arbitrary code</span>
		</div>

		<section class="surface-card registry-card">
			<header>
				<div>
					<div class="eyebrow">Company layer</div>
					<h2>Extension points</h2>
				</div>
			</header>
			<div v-if="loading" class="loading">
				<Skeleton v-for="index in 5" :key="index" height="58px" />
			</div>
			<DataTable v-else :value="workspace.extension_points" striped-rows>
				<Column field="label" header="Capability" />
				<Column field="description" header="Purpose" />
				<Column field="requirement" header="Contract" />
				<Column field="configured" header="Installed" />
				<Column field="status" header="Status">
					<template #body="{ data }">
						<Tag
							:value="data.status"
							:severity="data.status === 'Healthy' ? 'success' : 'warn'"
							rounded
						/>
					</template>
				</Column>
			</DataTable>
		</section>

		<div class="connector-grid">
			<section class="surface-card registry-card">
				<header>
					<div>
						<div class="eyebrow">External AI</div>
						<h2>MCP tool allowlist</h2>
					</div>
					<Tag :value="`${workspace.mcp_tools.length} tools`" severity="info" rounded />
				</header>
				<div class="capability-list">
					<div v-for="tool in workspace.mcp_tools" :key="tool.name">
						<Bot :size="15" />
						<span
							><strong>{{ tool.name }}</strong
							><small>{{ tool.description }}</small></span
						>
					</div>
				</div>
			</section>

			<section class="surface-card registry-card">
				<header>
					<div>
						<div class="eyebrow">Flow engine</div>
						<h2>Registered actions</h2>
					</div>
					<Tag
						:value="`${workspace.flow_actions.length} actions`"
						severity="success"
						rounded
					/>
				</header>
				<div class="capability-list compact">
					<div v-for="action in workspace.flow_actions" :key="action">
						<Braces :size="15" />
						<span
							><strong>{{ action }}</strong
							><small>Typed and explicitly registered</small></span
						>
					</div>
				</div>
			</section>
		</div>
	</template>
</template>

<style scoped>
	.summary-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 16px;
	}

	.summary-grid article {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 17px;
		color: var(--wa-success);
	}

	.summary-grid small,
	.summary-grid strong {
		display: block;
	}

	.summary-grid small {
		color: var(--wa-muted);
		font-size: 12px;
	}

	.summary-grid strong {
		margin-top: 4px;
		color: var(--wa-text);
		font-size: 20px;
	}

	.endpoint-card {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 13px 16px;
		margin-bottom: 16px;
		border: 1px solid color-mix(in srgb, var(--wa-success) 24%, var(--wa-border));
		border-radius: 14px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}

	.endpoint-card div {
		flex: 1;
	}

	.endpoint-card strong,
	.endpoint-card code {
		display: block;
	}

	.endpoint-card code {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.endpoint-card span {
		color: var(--wa-muted);
		font-size: 12px;
	}

	.registry-card {
		overflow: hidden;
		margin-bottom: 16px;
	}

	.registry-card header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 17px 18px;
		border-bottom: 1px solid var(--wa-border);
	}

	h2 {
		margin: 3px 0 0;
		font-size: 15px;
	}

	.connector-grid {
		display: grid;
		grid-template-columns: 1.35fr 0.65fr;
		gap: 16px;
	}

	.capability-list {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 1px;
		background: var(--wa-border);
	}

	.capability-list.compact {
		grid-template-columns: 1fr;
	}

	.capability-list > div {
		display: flex;
		align-items: flex-start;
		gap: 9px;
		padding: 13px 15px;
		background: var(--wa-surface);
	}

	.capability-list svg {
		flex: 0 0 auto;
		margin-top: 2px;
		color: var(--wa-success);
	}

	.capability-list strong,
	.capability-list small {
		display: block;
	}

	.capability-list strong {
		font-size: 12px;
	}

	.capability-list small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.4;
	}

	@media (max-width: 980px) {
		.connector-grid,
		.summary-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
