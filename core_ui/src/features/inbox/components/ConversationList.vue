<script setup>
	import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
	import Tag from 'primevue/tag'
	import { Building2, Headphones, MessageCircleMore, Store, UsersRound } from 'lucide-vue-next'

	const props = defineProps({
		rows: { type: Array, default: () => [] },
		selected: { type: String, default: '' },
		restoreScroll: { type: Number, default: 0 },
	})

	const emit = defineEmits(['select', 'scroll-position'])
	const list = ref(null)
	const scrollTop = ref(0)
	const viewportHeight = ref(600)
	let restored = false
	let resizeObserver = null
	const itemHeight = 78
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
			<button
				v-for="item in visibleRows"
				:key="item.row.name"
				:class="['conversation-row', { selected: item.row.name === selected }]"
				:style="{ transform: `translateY(${item.index * itemHeight}px)` }"
				:aria-posinset="item.index + 1"
				:aria-setsize="rows.length"
				@click="emit('select', item.row.name)"
			>
				<span class="avatar">{{
					(item.row.display_name || 'WA').slice(0, 2).toUpperCase()
				}}</span>
				<span class="conversation-copy">
					<span class="row-heading">
						<strong>{{ item.row.display_name }}</strong>
						<time>{{ item.row.last_message_at || '' }}</time>
					</span>
					<span class="preview">{{
						item.row.latest_message?.body || 'Media or new conversation'
					}}</span>
					<span class="row-meta">
						<em v-if="visibleTeam(item.row)" class="team-label">
							<component :is="teamIcon(visibleTeam(item.row).icon)" :size="12" />
							{{ visibleTeam(item.row).team_name }}
							<small v-if="item.row.contact_teams?.length > 1"
								>+{{ item.row.contact_teams.length - 1 }}</small
							>
						</em>
						<em v-else>{{ item.row.identity_status || 'WhatsApp contact' }}</em>
						<Tag
							v-if="item.row.unread_count"
							:value="item.row.unread_count"
							severity="success"
							rounded
						/>
					</span>
				</span>
			</button>
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
		height: 78px;
		box-sizing: border-box;
		display: grid;
		grid-template-columns: 42px minmax(0, 1fr);
		gap: 11px;
		padding: 12px 14px;
		border: 0;
		border-bottom: 1px solid var(--wa-border-soft);
		text-align: left;
		background: var(--wa-surface);
		cursor: pointer;
		contain: strict;
	}
	.conversation-row:hover,
	.conversation-row.selected {
		background: var(--wa-primary-soft);
	}
	.conversation-row:focus-visible {
		z-index: 1;
		outline: 2px solid var(--wa-primary);
		outline-offset: -2px;
	}
	.conversation-row.selected {
		box-shadow: inset 3px 0 var(--wa-primary);
	}
	.avatar {
		display: grid;
		place-items: center;
		width: 42px;
		height: 42px;
		border-radius: 50%;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		font-size: 12px;
		font-weight: 800;
	}
	.conversation-copy,
	.row-heading,
	.row-meta {
		min-width: 0;
		display: flex;
	}
	.conversation-copy {
		flex-direction: column;
		gap: 4px;
	}
	.row-heading,
	.row-meta {
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
		font-size: 13px;
	}
	time,
	.row-meta em {
		color: var(--wa-muted);
		font-size: 12px;
		font-style: normal;
	}
	.team-label {
		min-width: 0;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}
	.team-label small {
		font-size: 10px;
		font-style: normal;
	}
	.preview {
		color: var(--wa-muted);
		font-size: 12px;
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
