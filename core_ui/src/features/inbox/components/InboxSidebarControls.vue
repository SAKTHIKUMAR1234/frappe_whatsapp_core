<script setup>
	import Button from 'primevue/button'
	import IconField from 'primevue/iconfield'
	import InputIcon from 'primevue/inputicon'
	import InputText from 'primevue/inputtext'
	import { MessageSquarePlus, RefreshCw, Search, UsersRound } from 'lucide-vue-next'
	import InboxFolderTabs from '@/features/inbox/components/InboxFolderTabs.vue'
	import TeamSelect from '@/features/teams/components/TeamSelect.vue'

	defineProps({
		loading: { type: Boolean, default: false },
		canManage: { type: Boolean, default: false },
		search: { type: String, default: '' },
		mode: { type: String, default: 'all' },
		team: { type: String, default: '' },
		folder: { type: String, default: '' },
		folders: { type: Array, default: () => [] },
		unreadConversations: { type: Number, default: 0 },
	})

	const emit = defineEmits([
		'refresh',
		'new-chat',
		'new-folder',
		'update:search',
		'update:mode',
		'update:team',
		'update:folder',
	])

	function showAllConversations() {
		emit('update:mode', 'all')
		emit('update:folder', '')
	}

	function showUnreadConversations() {
		emit('update:mode', 'unread')
		emit('update:folder', '')
	}

	function showFolder(selectedFolder) {
		emit('update:mode', 'all')
		emit('update:folder', selectedFolder)
	}
</script>

<template>
	<div class="sidebar-controls">
		<header class="inbox-heading">
			<h1>WhatsApp</h1>
			<div class="heading-actions">
				<Button
					text
					rounded
					aria-label="Refresh conversations"
					:loading="loading"
					:disabled="loading"
					@click="$emit('refresh')"
				>
					<RefreshCw :size="17" />
				</Button>
				<Button
					v-if="canManage"
					text
					rounded
					aria-label="Start a new chat"
					@click="$emit('new-chat')"
				>
					<MessageSquarePlus :size="18" />
				</Button>
			</div>
		</header>
		<IconField class="conversation-search">
			<InputIcon><Search :size="16" /></InputIcon>
			<InputText
				:model-value="search"
				placeholder="Search or start a new chat"
				@update:model-value="$emit('update:search', $event)"
			/>
		</IconField>
		<InboxFolderTabs
			:mode="mode"
			:folder="folder"
			:folders="folders"
			:unread-conversations="unreadConversations"
			@select-all="showAllConversations"
			@select-unread="showUnreadConversations"
			@select-folder="showFolder"
			@new-folder="$emit('new-folder')"
		/>
		<div class="team-filter-row">
			<UsersRound :size="15" aria-hidden="true" />
			<span class="team-filter-label">Team</span>
			<TeamSelect
				:model-value="team"
				class="team-filter"
				placeholder="All teams"
				aria-label="Filter conversations by contact team"
				@update:model-value="$emit('update:team', $event || '')"
			/>
		</div>
	</div>
</template>

<style scoped>
	.sidebar-controls {
		display: contents;
	}
	.inbox-heading {
		height: 64px;
		padding: 0 16px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		border-bottom: 1px solid var(--wa-border);
		background: var(--wa-surface-muted);
	}
	.inbox-heading h1 {
		margin: 0;
		font-size: 21px;
		font-weight: 650;
		letter-spacing: -0.02em;
	}
	.heading-actions {
		display: flex;
		gap: 8px;
	}
	.conversation-search {
		margin: 8px 12px 3px;
		color: var(--wa-muted);
	}
	.conversation-search :deep(input) {
		width: 100%;
		height: 40px;
		padding-block: 9px;
		border: 0;
		border-radius: 8px;
		box-shadow: none;
		background: var(--wa-surface-muted);
		font-size: 14px;
	}
	.team-filter-row {
		min-width: 0;
		padding: 7px 12px 9px;
		display: flex;
		align-items: center;
		gap: 8px;
		border-bottom: 1px solid var(--wa-border);
		color: var(--wa-muted);
	}
	.team-filter {
		min-width: 0;
		flex: 1;
		border-radius: 8px;
		background: var(--wa-surface-muted);
	}
	.team-filter-label {
		font-size: 11px;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.045em;
	}
	.team-filter :deep(.p-select-label),
	.team-filter :deep(.p-autocomplete-input) {
		padding-block: 6px;
		font-size: 13px;
	}
	@media (max-width: 760px) {
		.inbox-heading {
			height: 60px;
			padding: 0 12px;
		}
		.heading-actions :deep(.p-button) {
			min-width: 44px;
			min-height: 44px;
		}
		.team-filter-row {
			padding-inline: 9px;
		}
		.team-filter {
			min-height: 44px;
		}
		.team-filter :deep(.p-autocomplete-input) {
			min-height: 44px;
		}
	}
</style>
