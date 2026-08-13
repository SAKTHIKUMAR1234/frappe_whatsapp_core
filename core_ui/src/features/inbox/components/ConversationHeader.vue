<script setup>
	import Button from 'primevue/button'
	import { ChevronLeft, PanelRight, Search } from 'lucide-vue-next'

	const props = defineProps({
		displayName: { type: String, default: '' },
		identity: { type: String, default: '' },
		status: { type: String, default: '' },
		contextOpen: { type: Boolean, default: false },
	})

	defineEmits(['back', 'search', 'toggle-context'])

	function initials() {
		return (props.displayName || 'WA').slice(0, 2).toUpperCase()
	}
</script>

<template>
	<header class="chat-heading">
		<Button
			class="mobile-back"
			unstyled
			aria-label="Back to conversations"
			@click="$emit('back')"
		>
			<ChevronLeft :size="18" />
		</Button>
		<span class="chat-avatar" aria-hidden="true">{{ initials() }}</span>
		<div class="chat-identity">
			<strong>{{ displayName }}</strong>
			<span>{{ identity }}</span>
		</div>
		<div class="chat-heading-actions">
			<span class="conversation-status">{{ status }}</span>
			<Button text rounded aria-label="Search this conversation" @click="$emit('search')">
				<Search :size="17" />
			</Button>
			<Button
				text
				rounded
				:aria-label="
					contextOpen ? 'Hide conversation details' : 'Show conversation details'
				"
				@click="$emit('toggle-context')"
			>
				<PanelRight :size="17" />
			</Button>
		</div>
	</header>
</template>

<style scoped>
	.chat-heading {
		height: 64px;
		padding: 10px 16px;
		display: flex;
		align-items: center;
		border-bottom: 1px solid var(--wa-border);
		background: var(--wa-surface-muted);
	}
	.mobile-back {
		display: none;
		padding: 5px;
		border: 0;
		background: transparent;
		color: var(--wa-text);
		cursor: pointer;
	}
	.chat-avatar {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		margin: 0 10px 0 2px;
		flex: 0 0 40px;
		border-radius: 50%;
		color: var(--wa-text);
		background: color-mix(in srgb, var(--wa-muted) 25%, var(--wa-surface));
		font-size: 12px;
		font-weight: 750;
	}
	.chat-identity {
		min-width: 0;
		margin-right: auto;
	}
	.chat-identity strong,
	.chat-identity span {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.chat-identity strong {
		font-size: 16px;
		font-weight: 600;
	}
	.chat-identity span,
	.conversation-status {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.chat-heading-actions {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	@media (max-width: 760px) {
		.chat-heading {
			min-width: 0;
			padding-inline: 8px;
		}
		.mobile-back {
			display: inline-flex;
		}
		.conversation-status {
			display: none;
		}
	}
</style>
