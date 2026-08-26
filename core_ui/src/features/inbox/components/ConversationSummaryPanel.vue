<script setup>
	import Tag from 'primevue/tag'
	import Button from 'primevue/button'
	import {
		AlertTriangle,
		Bot,
		CheckCircle2,
		ListChecks,
		MessagesSquare,
		MessageSquareText,
		Sparkles,
		Target,
		UsersRound,
	} from 'lucide-vue-next'
	import { computed } from 'vue'
	import { formatDateTime } from '@/utils/datetime'
	import ConversationThreadsPanel from '@/features/inbox/components/ConversationThreadsPanel.vue'

	const props = defineProps({
		data: { type: Object, required: true },
		canManage: { type: Boolean, default: false },
		loading: { type: Boolean, default: false },
	})
	defineEmits(['refresh', 'open-thread', 'comment-summary', 'expand'])

	const summary = computed(() => props.data.contact_summary || {})
	const teams = computed(() => {
		const rows = [props.data.assigned_team_details, ...(props.data.contact_teams || [])]
		return [...new Map(rows.filter(Boolean).map((row) => [row.name, row])).values()]
	})
	const readerCoverage = computed(() => {
		const expected = props.data.expected_readers || []
		const readers = new Set((props.data.readers || []).map((row) => row.user))
		return {
			read: expected.filter((row) => readers.has(row.user)),
			missing: expected.filter((row) => !readers.has(row.user)),
		}
	})
	const missingReaderNames = computed(() =>
		readerCoverage.value.missing.map((row) => row.display_name),
	)
	const missingReaderPreview = computed(() => {
		const visible = missingReaderNames.value.slice(0, 3)
		const remaining = missingReaderNames.value.length - visible.length
		return remaining > 0 ? `${visible.join(', ')} +${remaining} more` : visible.join(', ')
	})
</script>

<template>
	<div class="summary-workspace">
		<section class="summary-hero">
			<div class="summary-icon"><Sparkles :size="21" /></div>
			<div>
				<h2>{{ data.display_name }}</h2>
				<p v-if="summary.summary">{{ summary.summary }}</p>
				<p v-else>No summary yet.</p>
			</div>
			<div class="summary-actions">
				<Button label="Internal note" outlined @click="$emit('comment-summary')">
					<template #icon><MessageSquareText :size="15" /></template>
				</Button>
				<Button label="Expand conversation" @click="$emit('expand')">
					<template #icon><MessagesSquare :size="15" /></template>
				</Button>
				<Button
					v-if="canManage"
					aria-label="Refresh summary"
					text
					rounded
					:loading="loading"
					@click="$emit('refresh')"
					><Bot :size="15"
				/></Button>
			</div>
		</section>

		<div class="summary-grid">
			<section class="summary-card">
				<header><Target :size="16" /> Current intent</header>
				<strong>{{ summary.primary_intent || 'Not classified yet' }}</strong>
				<div v-if="summary.categories?.length" class="tag-row">
					<Tag
						v-for="category in summary.categories"
						:key="category"
						:value="category"
						severity="info"
						rounded
					/>
				</div>
			</section>
			<section class="summary-card">
				<header><UsersRound :size="16" /> Ownership</header>
				<div class="team-stack">
					<span v-for="team in teams" :key="team.name">{{ team.team_name }}</span>
					<span v-if="!teams.length">Unassigned queue</span>
				</div>
				<small>{{ data.conversation.status }} conversation</small>
			</section>
			<section class="summary-card">
				<header><MessagesSquare :size="16" /> Context coverage</header>
				<strong>{{ summary.message_count || 0 }} messages summarized</strong>
				<small v-if="summary.last_generated_at">
					Updated {{ formatDateTime(summary.last_generated_at) }}
				</small>
				<small v-else>Waiting for the first summary run</small>
			</section>
			<section class="summary-card">
				<header><CheckCircle2 :size="16" /> Team visibility</header>
				<strong>
					{{ readerCoverage.read.length }} of {{ data.expected_readers?.length || 0 }}
					teammates opened this chat
				</strong>
				<small v-if="readerCoverage.missing.length" :title="missingReaderNames.join(', ')">
					Waiting for {{ missingReaderPreview }}
				</small>
				<small v-else-if="data.expected_readers?.length">Visible to the whole team</small>
				<small v-else>No team readers are assigned</small>
			</section>
		</div>

		<div class="summary-detail-grid">
			<section class="summary-card detail-card">
				<header><ListChecks :size="16" /> Next actions</header>
				<ul v-if="summary.action_items?.length">
					<li v-for="item in summary.action_items" :key="item">{{ item }}</li>
				</ul>
				<div v-else class="empty-detail">No follow-up action is currently identified.</div>
			</section>
			<section class="summary-card detail-card risk-card">
				<header><AlertTriangle :size="16" /> Risks and blockers</header>
				<ul v-if="summary.risks?.length">
					<li v-for="risk in summary.risks" :key="risk">{{ risk }}</li>
				</ul>
				<div v-else class="empty-detail">No risks are currently identified.</div>
			</section>
		</div>

		<ConversationThreadsPanel
			:topics="data.topics || []"
			@open="$emit('open-thread', $event)"
			@comment="$emit('comment-summary', $event)"
		/>
	</div>
</template>

<style scoped>
	.summary-workspace {
		container: summary-workspace / inline-size;
		min-height: 0;
		flex: 1;
		overflow-y: auto;
		padding: 22px;
		background:
			radial-gradient(
				circle at 92% 0,
				color-mix(in srgb, var(--wa-primary) 10%, transparent),
				transparent 35%
			),
			var(--wa-chat-bg);
	}
	.summary-hero,
	.summary-card {
		border: 1px solid var(--wa-border);
		background: color-mix(in srgb, var(--wa-surface) 94%, transparent);
		box-shadow: var(--wa-shadow-card);
	}
	.summary-hero {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: start;
		gap: 14px;
		padding: 20px;
		border-radius: 18px;
	}
	.summary-icon {
		display: grid;
		place-items: center;
		width: 42px;
		height: 42px;
		border-radius: 13px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
	}
	.summary-actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		flex-wrap: wrap;
	}
	h2 {
		margin: 4px 0 8px;
		font-size: 20px;
	}
	.summary-hero p {
		max-width: 820px;
		margin: 0;
		color: var(--wa-muted);
		line-height: 1.65;
	}
	.summary-grid,
	.summary-detail-grid {
		display: grid;
		gap: 14px;
		margin-top: 14px;
	}
	.summary-grid {
		grid-template-columns: repeat(4, minmax(0, 1fr));
	}
	.summary-detail-grid {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
	.summary-card {
		min-width: 0;
		padding: 16px;
		border-radius: 15px;
	}
	.summary-card header {
		display: flex;
		align-items: center;
		gap: 7px;
		margin-bottom: 12px;
		color: var(--wa-muted);
		font-size: 11px;
		font-weight: 800;
		text-transform: uppercase;
	}
	.summary-card strong,
	.summary-card small {
		display: block;
	}
	.summary-card strong {
		line-height: 1.45;
	}
	.summary-card small {
		margin-top: 6px;
		color: var(--wa-muted);
		line-height: 1.45;
	}
	.tag-row,
	.team-stack {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 10px;
	}
	.team-stack span {
		padding: 4px 8px;
		border-radius: 999px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		font-size: 11px;
		font-weight: 700;
	}
	.detail-card ul {
		margin: 0;
		padding-left: 18px;
		line-height: 1.65;
	}
	.detail-card li + li {
		margin-top: 6px;
	}
	.risk-card header {
		color: var(--wa-warning);
	}
	.empty-detail {
		color: var(--wa-muted);
		font-size: 12px;
	}
	@media (max-width: 1100px) {
		.summary-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
	@container summary-workspace (max-width: 900px) {
		.summary-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
		.summary-hero {
			grid-template-columns: auto minmax(0, 1fr);
		}
		.summary-actions {
			grid-column: 1 / -1;
			justify-content: flex-start;
		}
	}
	@container summary-workspace (max-width: 560px) {
		.summary-grid,
		.summary-detail-grid {
			grid-template-columns: 1fr;
		}
	}
	@media (max-width: 700px) {
		.summary-workspace {
			padding: 12px;
		}
		.summary-hero {
			grid-template-columns: auto minmax(0, 1fr);
		}
		.summary-hero :deep(.p-button) {
			grid-column: 1 / -1;
		}
		.summary-grid,
		.summary-detail-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
