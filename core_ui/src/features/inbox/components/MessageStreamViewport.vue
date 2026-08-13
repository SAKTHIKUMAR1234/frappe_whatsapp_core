<script setup>
	import { ref } from 'vue'

	const emit = defineEmits(['scroll'])
	const viewport = ref(null)

	defineExpose({
		get scrollHeight() {
			return viewport.value?.scrollHeight || 0
		},
		get clientHeight() {
			return viewport.value?.clientHeight || 0
		},
		get scrollTop() {
			return viewport.value?.scrollTop || 0
		},
		set scrollTop(value) {
			if (viewport.value) viewport.value.scrollTop = value
		},
		scrollTo: (options) => viewport.value?.scrollTo(options),
		getBoundingClientRect: () => viewport.value?.getBoundingClientRect(),
		querySelectorAll: (selector) => viewport.value?.querySelectorAll(selector) || [],
	})
</script>

<template>
	<div ref="viewport" class="message-stream-viewport" @scroll.passive="emit('scroll', $event)">
		<slot />
	</div>
</template>

<style scoped>
	.message-stream-viewport {
		min-height: 0;
		flex: 1;
		padding: 18px;
		overflow-x: hidden;
		overflow-y: auto;
		background-color: var(--wa-chat-bg);
		background-image:
			radial-gradient(
				circle at 16px 16px,
				color-mix(in srgb, var(--wa-muted) 14%, transparent) 1px,
				transparent 1.5px
			),
			radial-gradient(
				circle at 42px 38px,
				color-mix(in srgb, var(--wa-muted) 10%, transparent) 1px,
				transparent 1.5px
			);
		background-size:
			58px 58px,
			58px 58px;
	}
	@media (max-width: 760px) {
		.message-stream-viewport {
			padding: 12px 9px;
		}
	}
</style>
