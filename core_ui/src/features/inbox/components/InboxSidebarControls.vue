<script setup>
	import Button from 'primevue/button'
	import IconField from 'primevue/iconfield'
	import InputIcon from 'primevue/inputicon'
	import InputText from 'primevue/inputtext'
	import { MessageSquarePlus, RefreshCw, Search } from 'lucide-vue-next'
	import TeamSelect from '@/features/teams/components/TeamSelect.vue'

	defineProps({
		loading: { type: Boolean, default: false },
		canManage: { type: Boolean, default: false },
		search: { type: String, default: '' },
		mode: { type: String, default: 'all' },
		team: { type: String, default: '' },
	})

	defineEmits(['refresh', 'new-chat', 'update:search', 'update:mode', 'update:team'])
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
		<div class="filter-row" role="group" aria-label="Conversation filters">
			<Button
				label="All"
				:class="['filter-button', { active: mode === 'all' }]"
				:outlined="mode !== 'all'"
				size="small"
				@click="$emit('update:mode', 'all')"
			/>
			<Button
				label="Unread"
				:class="['filter-button', { active: mode === 'unread' }]"
				:outlined="mode !== 'unread'"
				size="small"
				@click="$emit('update:mode', 'unread')"
			/>
			<TeamSelect
				:model-value="team"
				class="team-filter"
				placeholder="Search teams"
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
	.filter-row {
		min-width: 0;
		padding: 5px 12px 9px;
		display: flex;
		align-items: center;
		gap: 7px;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.filter-row::-webkit-scrollbar {
		display: none;
	}
	.filter-row :deep(.p-button) {
		flex: 0 0 auto;
		min-height: 34px;
		padding-inline: 13px;
		border-radius: 999px;
		border-color: var(--wa-border);
		color: var(--wa-muted);
		background: transparent;
		transition:
			color 360ms var(--wa-motion-standard),
			border-color 360ms var(--wa-motion-standard),
			background-color 360ms var(--wa-motion-standard),
			transform 360ms var(--wa-motion-standard);
	}
	.filter-row :deep(.filter-button:hover) {
		border-color: color-mix(in srgb, var(--wa-primary) 55%, var(--wa-border));
		color: var(--wa-text);
		transform: translateY(-1px);
	}
	.filter-row :deep(.filter-button.active) {
		border-color: var(--wa-primary);
		color: #07161c;
		background: var(--wa-primary);
	}
	.team-filter {
		width: auto;
		min-width: 122px;
		min-height: 34px;
		flex: 0 0 auto;
		border-radius: 999px;
		background: var(--wa-surface-muted);
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
		.heading-actions :deep(.p-button),
		.filter-row :deep(.p-button) {
			min-width: 44px;
			min-height: 44px;
		}
		.team-filter {
			min-height: 44px;
		}
		.team-filter :deep(.p-autocomplete-input) {
			min-height: 44px;
		}
	}
</style>
