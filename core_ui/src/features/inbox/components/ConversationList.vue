<script setup>
	import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import Tag from 'primevue/tag'
	import { Building2, Headphones, MessageCircleMore, Store, UsersRound } from 'lucide-vue-next'
	import { formatConversationTime } from '@/utils/datetime'

	const props = defineProps({
		rows: { type: Array, default: () => [] },
		selected: { type: String, default: '' },
		restoreScroll: { type: Number, default: 0 },
	})

	const emit = defineEmits(['select', 'scroll-position', 'load-more'])
	const list = ref(null)
	const scrollTop = ref(0)
	const viewportHeight = ref(600)
	let restored = false
	let resizeObserver = null
	const itemHeight = 72
	const overscan = 8
	const teamIcons = {
		'building-2': Building2,
		headphones: Headphones,
		'message-circle-more': MessageCircleMore,
		store: Store,
		'users-round': UsersRound,
	}

	function teamIcon(icon) {
		return teamIcons[icon] || UsersRound
	}

	function visibleTeam(row) {
		return row.assigned_team_details || row.contact_teams?.[0] || null
	}

	const visibleStart = computed(() =>
		Math.max(0, Math.floor(scrollTop.value / itemHeight) - overscan),
	)
	const visibleEnd = computed(() =>
		Math.min(
			props.rows.length,
			Math.ceil((scrollTop.value + viewportHeight.value) / itemHeight) + overscan,
		),
	)
	const visibleRows = computed(() =>
		props.rows.slice(visibleStart.value, visibleEnd.value).map((row, offset) => ({
			row,
			index: visibleStart.value + offset,
		})),
	)
	const spacerHeight = computed(() => props.rows.length * itemHeight)

	function updateViewport() {
		viewportHeight.value = Math.max(list.value?.clientHeight || 0, itemHeight)
	}

	watch(
		() => props.rows,
		async (rows) => {
			await nextTick()
			if (!list.value) return
			updateViewport()
			const maximum = Math.max(0, spacerHeight.value - viewportHeight.value)
			if (!restored && rows.length) {
				list.value.scrollTop = Math.min(props.restoreScroll, maximum)
				restored = true
			} else if (list.value.scrollTop > maximum) {
				list.value.scrollTop = maximum
			}
			scrollTop.value = list.value.scrollTop
		},
		{ immediate: true },
	)

	function rememberScroll() {
		scrollTop.value = list.value?.scrollTop || 0
		emit('scroll-position', scrollTop.value)
		if (
			list.value &&
			list.value.scrollHeight - list.value.clientHeight - list.value.scrollTop <= 160
		)
			emit('load-more')
	}

	onMounted(() => {
		updateViewport()
		if (typeof ResizeObserver !== 'undefined' && list.value) {
			resizeObserver = new ResizeObserver(updateViewport)
			resizeObserver.observe(list.value)
		}
	})

	onBeforeUnmount(() => resizeObserver?.disconnect())
</script>

<template>
	<div ref="list" class="conversation-list" @scroll.passive="rememberScroll">
		<div
			v-if="rows.length"
			class="conversation-spacer"
			:style="{ height: `${spacerHeight}px` }"
		>
			<Button
				v-for="item in visibleRows"
				:key="item.row.name"
				:class="['conversation-row', { selected: item.row.name === selected }]"
				:style="{ transform: `translateY(${item.index * itemHeight}px)` }"
				:aria-posinset="item.index + 1"
				:aria-setsize="rows.length"
				unstyled
				@click="emit('select', item.row.name)"
			>
				<span class="avatar">{{
					(item.row.display_name || 'WA').slice(0, 2).toUpperCase()
				}}</span>
				<span class="conversation-copy">
					<span class="row-heading">
						<span class="name-line">
							<strong>{{ item.row.display_name }}</strong>
							<component
								:is="teamIcon(visibleTeam(item.row).icon)"
								v-if="visibleTeam(item.row)"
								:size="13"
								:title="visibleTeam(item.row).team_name"
							/>
						</span>
						<time :datetime="item.row.last_message_at || undefined">{{
							formatConversationTime(item.row.last_message_at)
						}}</time>
					</span>
					<span class="preview-line">
						<span class="preview">{{
							item.row.latest_message?.body || 'Media or new conversation'
						}}</span>
						<Tag
							v-if="item.row.unread_count"
							:value="item.row.unread_count"
							severity="success"
							rounded
						/>
					</span>
				</span>
			</Button>
		</div>
		<div v-if="!rows.length" class="empty">
			<MessageCircleMore :size="30" />
			<strong>No conversations found</strong>
			<span>Start a template conversation or wait for an inbound message.</span>
		</div>
	</div>
</template>

<style scoped>
	.conversation-list {
		position: relative;
		min-height: 0;
		overflow-y: auto;
	}
	.conversation-spacer {
		position: relative;
		width: 100%;
	}
	.conversation-row {
		position: absolute;
		top: 0;
		left: 0;
		width: 100%;
		height: 72px;
		box-sizing: border-box;
		display: grid;
		grid-template-columns: 48px minmax(0, 1fr);
		gap: 12px;
		padding: 12px 13px;
		border: 0;
		border-bottom: 1px solid var(--wa-border-soft);
		text-align: left;
		background: var(--wa-surface);
		cursor: pointer;
		contain: strict;
		will-change: transform;
		transition:
			transform 220ms cubic-bezier(0.22, 1, 0.36, 1),
			background-color 140ms ease;
	}
	.conversation-row:hover,
	.conversation-row.selected {
		background: var(--wa-surface-muted);
	}
	.conversation-row:focus-visible {
		z-index: 1;
		outline: 2px solid var(--wa-primary);
		outline-offset: -2px;
	}
	.conversation-row.selected {
		box-shadow: none;
	}
	.avatar {
		display: grid;
		place-items: center;
		width: 48px;
		height: 48px;
		border-radius: 50%;
		color: var(--wa-text);
		background: color-mix(in srgb, var(--wa-muted) 24%, var(--wa-surface));
		font-size: 14px;
		font-weight: 650;
		transition:
			background-color 140ms ease,
			color 140ms ease;
	}
	.conversation-copy,
	.row-heading,
	.preview-line {
		min-width: 0;
		display: flex;
	}
	.conversation-copy {
		flex-direction: column;
		gap: 4px;
	}
	.row-heading,
	.preview-line {
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.row-heading strong,
	.preview {
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}
	.row-heading strong {
		font-size: 15px;
		font-weight: 600;
	}
	.name-line {
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 5px;
	}
	.name-line > svg {
		flex: 0 0 auto;
		color: var(--wa-muted);
	}
	time {
		color: var(--wa-muted);
		font-size: 12px;
	}
	.preview {
		color: var(--wa-muted);
		font-size: 13.5px;
	}
	.empty {
		min-height: 300px;
		display: grid;
		place-content: center;
		justify-items: center;
		gap: 8px;
		padding: 30px;
		color: var(--wa-muted);
		text-align: center;
	}
	.empty strong {
		color: var(--wa-text);
		font-size: 12px;
	}
	.empty span {
		max-width: 230px;
		font-size: 12px;
		line-height: 1.5;
	}
</style>
