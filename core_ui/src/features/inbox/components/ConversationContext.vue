<script setup>
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import { Bot, RefreshCw, UserRoundCheck } from 'lucide-vue-next'
	import Button from 'primevue/button'

	defineProps({
		data: { type: Object, required: true },
		canManage: { type: Boolean, default: false },
	})

	defineEmits(['status', 'refresh-summary'])

	const statusOptions = ['Open', 'Pending', 'Resolved']
</script>

<template>
	<aside class="context-panel">
		<section>
			<div class="eyebrow">Conversation</div>
			<div class="identity">
				<span>{{ (data.display_name || 'WA').slice(0, 2).toUpperCase() }}</span>
				<div>
					<strong>{{ data.display_name }}</strong>
					<small>{{ data.identity?.normalized_value }}</small>
				</div>
			</div>
			<Select
				v-if="canManage"
				:model-value="data.conversation?.status"
				:options="statusOptions"
				class="status-select"
				@update:model-value="$emit('status', $event)"
			/>
			<span v-else class="status-readonly">{{ data.conversation?.status }}</span>
		</section>

		<section>
			<header><UserRoundCheck :size="15" /> Team visibility</header>
			<div class="reader-list">
				<Tag
					v-for="reader in data.readers"
					:key="reader.user"
					:value="reader.user"
					severity="secondary"
					rounded
				/>
				<span v-if="!data.readers?.length" class="empty-copy"
					>Not read by the team yet.</span
				>
			</div>
		</section>

		<section class="ai-note">
			<header>
				<span><Bot :size="15" /> Contact summary</span>
				<Button
					v-if="canManage"
					text
					rounded
					aria-label="Refresh contact summary"
					@click="$emit('refresh-summary')"
				>
					<RefreshCw :size="14" />
				</Button>
			</header>
			<p v-if="data.contact_summary?.summary">{{ data.contact_summary.summary }}</p>
			<p v-else>No summary has been generated for this contact yet.</p>
			<div v-if="data.contact_summary?.categories?.length" class="summary-tags">
				<Tag
					v-for="category in data.contact_summary.categories"
					:key="category"
					:value="category"
					severity="info"
					rounded
				/>
			</div>
			<ul v-if="data.contact_summary?.action_items?.length" class="summary-actions">
				<li v-for="action in data.contact_summary.action_items" :key="action">
					{{ action }}
				</li>
			</ul>
		</section>
	</aside>
</template>

<style scoped>
	.context-panel {
		min-height: 0;
		overflow-y: auto;
		border-left: 1px solid var(--wa-border);
		background: var(--wa-surface);
	}
	section {
		padding: 17px;
		border-bottom: 1px solid var(--wa-border-soft);
	}
	section > header {
		display: flex;
		align-items: center;
		gap: 7px;
		margin-bottom: 12px;
		color: var(--wa-muted);
		font-size: 11px;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.ai-note > header {
		justify-content: space-between;
	}
	.ai-note > header > span {
		display: inline-flex;
		align-items: center;
		gap: 7px;
	}
	.identity {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 11px 0 13px;
	}
	.identity > span {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border-radius: 12px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		font-size: 12px;
		font-weight: 800;
	}
	.identity strong,
	.identity small {
		display: block;
	}
	.identity strong {
		font-size: 13px;
	}
	.identity small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.status-select {
		width: 100%;
	}
	.status-readonly {
		display: inline-flex;
		padding: 5px 9px;
		border-radius: 999px;
		background: var(--wa-surface-muted);
		color: var(--wa-muted);
		font-size: 12px;
		font-weight: 700;
	}
	.reader-list {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.ai-note {
		background: var(--wa-primary-soft);
	}
	.ai-note p {
		margin: 0;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.55;
	}
	.summary-tags {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		margin-top: 10px;
	}
	.summary-actions {
		margin: 10px 0 0;
		padding-left: 18px;
		color: var(--wa-text);
		font-size: 12px;
		line-height: 1.5;
	}
</style>
