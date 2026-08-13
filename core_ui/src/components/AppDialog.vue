<script setup>
	import { computed, nextTick, ref, useAttrs } from 'vue'
	import Dialog from 'primevue/dialog'

	defineOptions({ inheritAttrs: false })
	const props = defineProps({
		modelValue: { type: Boolean, default: undefined },
		visible: { type: Boolean, default: undefined },
		header: { type: String, default: '' },
		width: { type: String, default: '640px' },
	})
	const emit = defineEmits(['update:modelValue', 'update:visible', 'show', 'hide'])
	const attrs = useAttrs()
	const dialog = ref(null)
	const shown = computed(() => props.modelValue ?? props.visible ?? false)
	const dialogStyle = computed(() => ({
		width: props.width,
		maxWidth: 'calc(100vw - 24px)',
		...(attrs.style || {}),
	}))
	const dialogBreakpoints = computed(
		() => attrs.breakpoints || { '680px': 'calc(100vw - 24px)' },
	)

	function updateVisible(value) {
		emit('update:modelValue', value)
		emit('update:visible', value)
	}

	async function focusFirstControl() {
		await nextTick()
		const root = dialog.value?.$el
		const firstField = root?.querySelector?.(
			'input:not([disabled]), textarea:not([disabled]), select:not([disabled])',
		)
		const firstAction = root?.querySelector?.(
			'button:not([disabled]):not(.p-dialog-close-button)',
		)
		;(firstField || firstAction)?.focus?.()
		emit('show')
	}
</script>

<template>
	<Dialog
		v-bind="attrs"
		ref="dialog"
		:visible="shown"
		:header="props.header"
		modal
		:dismissable-mask="false"
		:draggable="false"
		:style="dialogStyle"
		:breakpoints="dialogBreakpoints"
		@update:visible="updateVisible"
		@show="focusFirstControl"
		@hide="emit('hide')"
	>
		<slot />
		<template #footer><slot name="footer" /></template>
	</Dialog>
</template>
