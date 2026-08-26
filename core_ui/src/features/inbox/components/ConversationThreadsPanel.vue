<script setup>
	import { computed } from 'vue'
	import Button from 'primevue/button'
	import Tag from 'primevue/tag'
	import { ArrowUpRight, MessageSquareText, MessagesSquare } from 'lucide-vue-next'
	import { formatDateTime } from '@/utils/datetime'
	import {
		presentConversationThreads,
		threadStatusTone,
	} from '@/features/inbox/utils/conversationThreads'

	const props = defineProps({
		topics: { type: Array, default: () => [] },
	})
	const emit = defineEmits(['open', 'comment'])
	const threads = computed(() => presentConversationThreads(props.topics))

	function timeRange(thread) {
		const start = formatDateTime(thread.startedAt, '')
		const end = formatDateTime(thread.endedAt, '')
		if (!start) return ''
		return end && end !== start ? `${start} – ${end}` : start
	}
</script>

<template>
	<section v-if="threads.length" class="threads-panel" aria-labelledby="threads-title">
		<header class="threads-heading">
			<span><MessagesSquare :size="16" /></span>
			<h3 id="threads-title">Conversation threads</h3>
			<strong>{{ threads.length }}</strong>
		</header>
		<div class="thread-list">
			<div v-for="thread in threads" :key="thread.name" class="thread-row">
				<Button
					unstyled
					class="thread-open"
					:disabled="!thread.firstMessage"
					:aria-label="`Open ${thread.title} in chat`"
					@click="emit('open', thread.firstMessage)"
				>
					<span class="thread-copy">
						<span class="thread-title-line">
							<strong>{{ thread.title }}</strong>
							<Tag
								:value="thread.status"
								:severity="threadStatusTone(thread.status)"
								rounded
							/>
						</span>
						<span v-if="thread.summary" class="thread-summary">{{
							thread.summary
						}}</span>
						<span class="thread-meta">
							<em v-if="thread.category">{{ thread.category }}</em>
							<span>{{ thread.messageCount }} messages</span>
							<time v-if="timeRange(thread)">{{ timeRange(thread) }}</time>
						</span>
					</span>
					<ArrowUpRight :size="17" aria-hidden="true" />
				</Button>
				<Button
					text
					rounded
					:aria-label="`Add internal note to ${thread.title}`"
					@click="
						emit('comment', {
							doctype: 'WhatsApp Core Conversation Topic',
							name: thread.name,
							label: thread.title,
						})
					"
				>
					<MessageSquareText :size="16" />
				</Button>
			</div>
		</div>
	</section>
</template>

<style scoped>
	.threads-panel {
		margin-top: 14px;
		border: 1px solid var(--wa-border);
		border-radius: 15px;
		background: color-mix(in srgb, var(--wa-surface) 96%, transparent);
		box-shadow: var(--wa-shadow-card);
		overflow: hidden;
	}
	.threads-heading {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 11px;
		padding: 14px 16px;
		border-bottom: 1px solid var(--wa-border-soft);
	}
	.threads-heading > span {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 10px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
	}
	.threads-heading h3 {
		display: block;
		margin: 0;
	}
	.threads-heading h3 {
		font-size: 14px;
	}
	.threads-heading > strong {
		min-width: 28px;
		padding: 4px 8px;
		border-radius: 999px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		font-size: 11px;
		text-align: center;
	}
	.thread-list {
		display: grid;
	}
	.thread-row {
		width: 100%;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: center;
		gap: 4px;
		padding: 4px 8px 4px 0;
		border: 0;
		border-bottom: 1px solid var(--wa-border-soft);
	}
	.thread-open {
		width: 100%;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: center;
		gap: 12px;
		padding: 10px 16px;
		border: 0;
		color: var(--wa-text);
		background: transparent;
		text-align: left;
		cursor: pointer;
		transition:
			background-color 160ms var(--wa-motion-standard),
			color 160ms var(--wa-motion-standard);
	}
	.thread-row:last-child {
		border-bottom: 0;
	}
	.thread-open:hover,
	.thread-open:focus-visible {
		background: var(--wa-surface-muted);
		outline: none;
	}
	.thread-open:focus-visible {
		box-shadow: inset 3px 0 var(--wa-primary);
	}
	.thread-open:disabled {
		cursor: default;
		opacity: 0.66;
	}
	.thread-copy,
	.thread-title-line,
	.thread-meta {
		min-width: 0;
		display: flex;
	}
	.thread-copy {
		flex-direction: column;
		gap: 6px;
	}
	.thread-title-line,
	.thread-meta {
		align-items: center;
		gap: 8px;
	}
	.thread-title-line strong {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 13px;
	}
	.thread-title-line :deep(.p-tag) {
		flex: 0 0 auto;
		padding: 2px 7px;
		font-size: 9px;
	}
	.thread-summary {
		display: -webkit-box;
		overflow: hidden;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.5;
	}
	.thread-meta {
		flex-wrap: wrap;
		color: var(--wa-muted);
		font-size: 10px;
	}
	.thread-meta > * + *::before {
		content: '•';
		margin-right: 8px;
		color: var(--wa-border);
	}
	.thread-meta em {
		color: var(--wa-primary);
		font-style: normal;
		font-weight: 700;
	}
	@media (max-width: 700px) {
		.thread-open {
			min-height: 58px;
			padding: 12px;
		}
		.thread-meta time {
			flex-basis: 100%;
		}
		.thread-meta time::before {
			display: none;
		}
	}
</style>
