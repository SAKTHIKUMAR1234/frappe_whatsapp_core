<script setup>
	import Button from 'primevue/button'
	import { Download, Info, ListTodo, Reply } from 'lucide-vue-next'

	defineProps({
		visible: { type: Boolean, default: false },
		position: { type: Object, default: () => ({ x: 0, y: 0 }) },
		canReply: { type: Boolean, default: false },
		canDownload: { type: Boolean, default: false },
		selectedForInternalTask: { type: Boolean, default: false },
		reactions: { type: Array, default: () => [] },
	})

	defineEmits(['close', 'react', 'reply', 'info', 'download', 'internal-task'])
</script>

<template>
	<Teleport to="body">
		<div
			v-if="visible"
			class="message-menu-layer"
			role="presentation"
			@click.self="$emit('close')"
			@contextmenu.prevent
		>
			<div
				class="message-action-menu"
				role="menu"
				aria-label="Message actions"
				:style="{ left: `${position.x}px`, top: `${position.y}px` }"
			>
				<div class="quick-reactions" aria-label="React to message">
					<Button
						v-for="emoji in reactions"
						:key="emoji"
						unstyled
						:aria-label="`React with ${emoji}`"
						@click="$emit('react', emoji)"
					>
						{{ emoji }}
					</Button>
				</div>
				<Button v-if="canReply" unstyled role="menuitem" @click="$emit('reply')">
					<Reply :size="17" /><span>Reply</span>
				</Button>
				<Button unstyled role="menuitem" @click="$emit('info')">
					<Info :size="17" /><span>Message info</span>
				</Button>
				<Button unstyled role="menuitem" @click="$emit('internal-task')">
					<ListTodo :size="17" />
					<span>{{
						selectedForInternalTask
							? 'Remove from internal task'
							: 'Add to internal task'
					}}</span>
				</Button>
				<Button v-if="canDownload" unstyled role="menuitem" @click="$emit('download')">
					<Download :size="17" /><span>Download</span>
				</Button>
			</div>
		</div>
	</Teleport>
</template>

<style scoped>
	.message-menu-layer {
		position: fixed;
		inset: 0;
		z-index: 12000;
	}
	.message-action-menu {
		position: fixed;
		z-index: 1;
		width: 190px;
		padding: 7px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		background: var(--wa-surface);
		box-shadow: var(--wa-shadow-lg);
		animation: message-menu-in 120ms ease;
	}
	.message-action-menu > :deep(button) {
		width: 100%;
		padding: 8px 9px;
		display: flex;
		align-items: center;
		gap: 9px;
		border: 0;
		border-radius: 7px;
		color: var(--wa-text);
		background: transparent;
		font: inherit;
		font-size: 12px;
		cursor: pointer;
	}
	.message-action-menu > :deep(button:hover) {
		background: var(--wa-surface-muted);
	}
	.quick-reactions {
		display: flex;
		justify-content: space-between;
		gap: 2px;
		padding-bottom: 6px;
		margin-bottom: 5px;
		border-bottom: 1px solid var(--wa-border-soft);
	}
	.quick-reactions :deep(button) {
		width: 27px;
		height: 27px;
		padding: 0;
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 50%;
		background: transparent;
		font-size: 16px;
		cursor: pointer;
	}
	.quick-reactions :deep(button:hover) {
		background: var(--wa-surface-muted);
	}
	@keyframes message-menu-in {
		from {
			opacity: 0;
			transform: translateY(-4px) scale(0.98);
		}
		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}
	@media (max-width: 760px) {
		.message-menu-layer {
			background: rgba(15, 23, 42, 0.28);
		}
		.message-action-menu {
			inset: auto 8px max(8px, env(safe-area-inset-bottom)) 8px !important;
			width: auto;
			padding: 9px;
			border-radius: 16px;
		}
		.message-action-menu > :deep(button) {
			min-height: 46px;
			font-size: 14px;
		}
		.quick-reactions {
			padding: 5px 3px 10px;
		}
		.quick-reactions :deep(button) {
			min-height: 42px;
			font-size: 22px;
		}
	}
</style>
