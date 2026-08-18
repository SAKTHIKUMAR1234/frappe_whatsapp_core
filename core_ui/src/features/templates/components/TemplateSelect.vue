<script setup>
	import { computed } from 'vue'
	import LinkField from '@/components/form/LinkField.vue'

	const props = defineProps({
		modelValue: { type: String, default: '' },
		options: { type: Array, default: () => [] },
		optionValue: { type: String, default: 'name' },
		placeholder: { type: String, default: 'Select a WhatsApp template' },
		disabled: { type: Boolean, default: false },
		showClear: { type: Boolean, default: true },
	})
	defineEmits(['update:modelValue', 'change'])

	const presentedOptions = computed(() =>
		(props.options || []).map((row) => {
			const option = row && typeof row === 'object' ? row : { [props.optionValue]: row }
			const value = option[props.optionValue] || option.name || option.template_name || ''
			return {
				...option,
				_link_value: value,
				_link_label: option.template_name || option.label || option.name || value,
				description: [option.language_code, option.category, option.approval_status]
					.filter(Boolean)
					.join(' · '),
			}
		}),
	)
</script>

<template>
	<LinkField
		:model-value="modelValue"
		:options="presentedOptions"
		option-label="_link_label"
		option-value="_link_value"
		:placeholder="placeholder"
		:disabled="disabled"
		:show-clear="showClear"
		:filter-fields="['_link_label', '_link_value', 'language_code', 'category']"
		@update:model-value="$emit('update:modelValue', $event)"
		@change="$emit('change', $event)"
	/>
</template>
