<script setup>
	import Button from 'primevue/button'

	const props = defineProps({
		width: { type: Number, required: true },
		minWidth: { type: Number, default: 270 },
		maxWidth: { type: Number, default: 620 },
	})

	const emit = defineEmits(['resize', 'reset'])
	let originX = 0
	let originWidth = 0

	function clamp(value) {
		return Math.max(props.minWidth, Math.min(props.maxWidth, Math.round(value)))
	}

	function stopResize() {
		window.removeEventListener('pointermove', resizeFromPointer)
		window.removeEventListener('pointerup', stopResize)
		document.documentElement.classList.remove('inbox-resizing')
	}

	function resizeFromPointer(event) {
		emit('resize', clamp(originWidth + event.clientX - originX))
	}

	function startResize(event) {
		originX = event.clientX
		originWidth = props.width
		document.documentElement.classList.add('inbox-resizing')
		window.addEventListener('pointermove', resizeFromPointer)
		window.addEventListener('pointerup', stopResize, { once: true })
	}

	function resizeFromKeyboard(event) {
		if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return
		event.preventDefault()
		if (event.key === 'Home') return emit('reset')
		const step = event.shiftKey ? 40 : 12
		emit('resize', clamp(props.width + (event.key === 'ArrowRight' ? step : -step)))
	}
</script>

<template>
	<Button
		unstyled
		class="resize-handle"
		role="separator"
		aria-label="Resize conversation list"
		aria-orientation="vertical"
		:aria-valuemin="minWidth"
		:aria-valuemax="maxWidth"
		:aria-valuenow="width"
		@pointerdown="startResize"
		@keydown="resizeFromKeyboard"
		@dblclick="$emit('reset')"
	>
		<span aria-hidden="true"></span>
	</Button>
</template>

<style scoped>
	.resize-handle {
		position: relative;
		z-index: 4;
		width: 5px;
		min-width: 5px;
		height: 100%;
		padding: 0;
		border: 0;
		background: var(--wa-border);
		cursor: col-resize;
		touch-action: none;
		transition: background-color 140ms ease;
	}
	.resize-handle:hover,
	.resize-handle:focus-visible {
		background: var(--wa-primary);
		outline: 0;
	}
	.resize-handle span {
		position: absolute;
		inset: 50% auto auto 50%;
		width: 3px;
		height: 36px;
		border-radius: 99px;
		background: color-mix(in srgb, var(--wa-text) 30%, transparent);
		transform: translate(-50%, -50%);
		opacity: 0;
		transition: opacity 140ms ease;
	}
	.resize-handle:hover span,
	.resize-handle:focus-visible span {
		opacity: 1;
	}
</style>
