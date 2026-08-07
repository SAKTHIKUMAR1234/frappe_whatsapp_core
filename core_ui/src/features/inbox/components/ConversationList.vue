<script setup>
	import { nextTick, ref, watch } from 'vue'
	import Tag from 'primevue/tag'
	import { MessageCircleMore } from 'lucide-vue-next'

	const props = defineProps({
		rows: { type: Array, default: () => [] },
		selected: { type: String, default: '' },
		restoreScroll: { type: Number, default: 0 },
	})

	const emit = defineEmits(['select', 'scroll-position'])
	const list = ref(null)
	let restored = false

	watch(
		() => props.rows.length,
		async (length) => {
			if (restored || !length) return
			await nextTick()
			if (list.value) list.value.scrollTop = props.restoreScroll
			restored = true
		},
		{ immediate: true },
	)

	function rememberScroll() {
		emit('scroll-position', list.value?.scrollTop || 0)
	}
</script>

<template>
	<div ref="list" class="conversation-list" @scroll.passive="rememberScroll">
		<button
			v-for="row in rows"
			:key="row.name"
			:class="['conversation-row', { selected: row.name === selected }]"
			@click="emit('select', row.name)"
		>
			<span class="avatar">{{ (row.display_name || 'WA').slice(0, 2).toUpperCase() }}</span>
			<span class="conversation-copy">
				<span class="row-heading">
					<strong>{{ row.display_name }}</strong>
					<time>{{ row.last_message_at || '' }}</time>
				</span>
				<span class="preview">{{
					row.latest_message?.body || 'Media or new conversation'
				}}</span>
				<span class="row-meta">
					<em>{{
						row.party_binding?.party_role || row.identity_status || 'Unmapped'
					}}</em>
					<Tag
						v-if="row.unread_count"
						:value="row.unread_count"
						severity="success"
						rounded
					/>
				</span>
			</span>
		</button>
		<div v-if="!rows.length" class="empty">
			<MessageCircleMore :size="30" />
			<strong>No conversations found</strong>
			<span>Start a template conversation or wait for an inbound message.</span>
		</div>
	</div>
</template>

<style scoped>
	.conversation-list {
		min-height: 0;
		overflow-y: auto;
	}
	.conversation-row {
		width: 100%;
		display: grid;
		grid-template-columns: 42px minmax(0, 1fr);
		gap: 11px;
		padding: 12px 14px;
		border: 0;
		border-bottom: 1px solid #edf1ef;
		text-align: left;
		background: white;
		cursor: pointer;
		content-visibility: auto;
		contain-intrinsic-size: 67px;
	}
	.conversation-row:hover,
	.conversation-row.selected {
		background: #eff9f5;
	}
	.conversation-row:focus-visible {
		position: relative;
		z-index: 1;
		outline: 2px solid #168a62;
		outline-offset: -2px;
	}
	.conversation-row.selected {
		box-shadow: inset 3px 0 #18a879;
	}
	.avatar {
		display: grid;
		place-items: center;
		width: 42px;
		height: 42px;
		border-radius: 50%;
		color: #0b5d48;
		background: #d9f6e9;
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
		color: #829088;
		font-size: 10px;
		font-style: normal;
	}
	.preview {
		color: #66756e;
		font-size: 11px;
	}
	.empty {
		min-height: 300px;
		display: grid;
		place-content: center;
		justify-items: center;
		gap: 8px;
		padding: 30px;
		color: #829088;
		text-align: center;
	}
	.empty strong {
		color: #34443d;
		font-size: 12px;
	}
	.empty span {
		max-width: 230px;
		font-size: 10px;
		line-height: 1.5;
	}
</style>
