<script setup>
	import { ref } from 'vue'
	import Button from 'primevue/button'
	import Textarea from 'primevue/textarea'
	import { Paperclip, Send, Smile, X } from 'lucide-vue-next'

	defineProps({
		modelValue: { type: String, default: '' },
		replyTo: { type: Object, default: null },
	})

	defineEmits(['update:modelValue', 'send', 'emoji', 'media', 'cancel-reply', 'typing', 'blur'])

	const input = ref(null)

	function focus(options = { preventScroll: true }) {
		const element = input.value?.$el?.querySelector?.('textarea') || input.value?.$el
		element?.focus?.(options)
	}

	defineExpose({ focus })
</script>

<template>
	<footer class="composer">
		<div v-if="replyTo" class="reply-preview">
			<span><strong>Replying to</strong> {{ replyTo.body || replyTo.message_type }}</span>
			<Button unstyled aria-label="Cancel reply" @click="$emit('cancel-reply')">
				<X :size="14" />
			</Button>
		</div>
		<Button text rounded aria-label="Add emoji" @click="$emit('emoji')"
			><Smile :size="20"
		/></Button>
		<Button text rounded aria-label="Send media or rich message" @click="$emit('media')">
			<Paperclip :size="20" />
		</Button>
		<Textarea
			ref="input"
			:model-value="modelValue"
			auto-resize
			rows="1"
			name="whatsapp_message"
			autocomplete="off"
			aria-label="Message"
			placeholder="Type a message…"
			@update:model-value="
				($event) => {
					$emit('update:modelValue', $event)
					$emit('typing')
				}
			"
			@keydown.enter.exact.prevent="$emit('send')"
			@blur="$emit('blur')"
		/>
		<Button
			:disabled="!modelValue.trim()"
			rounded
			aria-label="Send message"
			@click="$emit('send')"
		>
			<Send :size="18" />
		</Button>
	</footer>
</template>

<style scoped>
	.composer {
		padding: 10px 12px;
		display: flex;
		align-items: center;
		gap: 7px;
		flex-wrap: wrap;
		border-top: 1px solid var(--wa-border);
		background: var(--wa-surface-muted);
	}
	.reply-preview {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex: 1 0 100%;
		padding: 6px 9px;
		border-left: 3px solid var(--wa-success);
		border-radius: 6px;
		background: var(--wa-success-soft);
		font-size: 11px;
	}
	.reply-preview span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.reply-preview :deep(button) {
		display: inline-flex;
		border: 0;
		background: transparent;
		color: var(--wa-text);
		cursor: pointer;
	}
	.composer :deep(textarea) {
		min-width: 0;
		flex: 1;
		max-height: 110px;
		padding: 10px 14px;
		border: 0;
		border-radius: 10px;
		background: var(--wa-surface);
		box-shadow: none;
		font-size: 14px;
		transition:
			background-color 140ms ease,
			box-shadow 140ms ease;
	}
	.composer :deep(textarea:focus) {
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--wa-primary) 24%, transparent);
	}
	.composer :deep(.p-button) {
		transition:
			transform 120ms ease,
			background-color 120ms ease,
			color 120ms ease;
	}
	.composer :deep(.p-button:not(:disabled):hover) {
		transform: translateY(-1px);
	}
	.composer :deep(.p-button:not(:disabled):active) {
		transform: translateY(0) scale(0.96);
	}
</style>
