<script setup>
	import Button from 'primevue/button'
	import { Folder, FolderPlus, Inbox, Mail, Star } from 'lucide-vue-next'

	const props = defineProps({
		mode: { type: String, default: 'all' },
		folder: { type: String, default: '' },
		folders: { type: Array, default: () => [] },
		unreadConversations: { type: Number, default: 0 },
	})

	const emit = defineEmits(['select-all', 'select-unread', 'select-folder', 'new-folder'])

	function folderIsActive(item) {
		if (!props.folder) return false
		if (item.folder_type === 'Important') {
			return (
				props.folder === item.name ||
				(props.folder === 'important' && item.folder_type === 'Important')
			)
		}
		return props.folder === item.name
	}

	function badge(value) {
		const count = Number(value || 0)
		return count > 99 ? '99+' : String(count)
	}
</script>

<template>
	<nav class="folder-tabs" aria-label="Conversation folders">
		<Button
			unstyled
			:class="['folder-tab', { active: mode === 'all' && !folder }]"
			:aria-current="mode === 'all' && !folder ? 'page' : undefined"
			@click="$emit('select-all')"
		>
			<Inbox :size="15" />
			<span>All</span>
			<small v-if="unreadConversations" class="unread-badge">{{
				badge(unreadConversations)
			}}</small>
		</Button>
		<Button
			unstyled
			:class="['folder-tab', { active: mode === 'unread' && !folder }]"
			:aria-current="mode === 'unread' && !folder ? 'page' : undefined"
			@click="$emit('select-unread')"
		>
			<Mail :size="15" />
			<span>Unread</span>
			<small v-if="unreadConversations" class="unread-badge">{{
				badge(unreadConversations)
			}}</small>
		</Button>
		<Button
			v-for="item in folders"
			:key="item.name"
			unstyled
			:class="['folder-tab', { active: folderIsActive(item) }]"
			:aria-current="folderIsActive(item) ? 'page' : undefined"
			:title="item.folder_name"
			@click="$emit('select-folder', item.name)"
		>
			<Star v-if="item.folder_type === 'Important'" :size="15" />
			<Folder v-else :size="15" :style="{ color: item.color || undefined }" />
			<span>{{ item.folder_name }}</span>
			<small v-if="Number(item.unread_conversations || 0)" class="unread-badge">{{
				badge(item.unread_conversations)
			}}</small>
		</Button>
		<Button
			unstyled
			class="folder-tab add-folder"
			aria-label="Create contact folder"
			title="Create folder"
			@click="$emit('new-folder')"
		>
			<FolderPlus :size="16" />
			<span>New</span>
		</Button>
	</nav>
</template>

<style scoped>
	.folder-tabs {
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 5px;
		padding: 6px 12px 8px;
		overflow-x: auto;
		overflow-y: hidden;
		border-bottom: 1px solid var(--wa-border-soft);
		scrollbar-width: none;
		scroll-snap-type: x proximity;
	}
	.folder-tabs::-webkit-scrollbar {
		display: none;
	}
	.folder-tab {
		min-width: max-content;
		min-height: 34px;
		flex: 0 0 auto;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		padding: 6px 10px;
		border: 1px solid transparent;
		border-radius: 9px;
		color: var(--wa-muted);
		background: transparent;
		font: inherit;
		font-size: 12px;
		font-weight: 700;
		line-height: 1;
		white-space: nowrap;
		cursor: pointer;
		scroll-snap-align: start;
		transition:
			color 160ms ease,
			background-color 160ms ease,
			border-color 160ms ease;
	}
	.folder-tab:hover {
		color: var(--wa-text);
		background: var(--wa-surface-muted);
	}
	.folder-tab.active {
		border-color: color-mix(in srgb, var(--wa-primary) 28%, transparent);
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
	}
	.folder-tab.active :deep(svg) {
		stroke-width: 2.25;
	}
	.folder-tab span {
		max-width: 138px;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.unread-badge {
		min-width: 18px;
		height: 18px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0 5px;
		border-radius: 999px;
		color: white;
		background: var(--wa-primary);
		font-size: 9px;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	.add-folder {
		margin-left: 2px;
		border-style: dashed;
		border-color: var(--wa-border);
	}
	@media (max-width: 760px) {
		.folder-tabs {
			padding-inline: 9px;
		}
		.folder-tab {
			min-height: 40px;
			padding-inline: 11px;
		}
	}
</style>
