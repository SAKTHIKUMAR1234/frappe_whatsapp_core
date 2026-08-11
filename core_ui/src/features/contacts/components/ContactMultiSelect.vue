<script setup>
	import { computed } from 'vue'
	import MultiLinkField from '@/components/form/MultiLinkField.vue'
	import { call } from '@/services/frappe'

	const props = defineProps({
		modelValue: { type: Array, default: () => [] },
		options: { type: Array, default: () => [] },
		placeholder: { type: String, default: 'Search and select Core contacts' },
		disabled: { type: Boolean, default: false },
	})
	defineEmits(['update:modelValue', 'change'])

	function present(rows) {
		return (rows || []).map((row) => ({
			...row,
			description: [row.phone_number, row.reference].filter(Boolean).join(' · '),
		}))
	}
	const presentedOptions = computed(() => present(props.options))
	async function searchContacts(search) {
		return present(
			await call('frappe_whatsapp_core.frontend_api.search_contact_options', {
				search,
				limit: 50,
			}),
		)
	}
</script>

<template>
	<MultiLinkField
		:model-value="modelValue"
		:options="presentedOptions"
		option-label="label"
		option-value="identity"
		:placeholder="placeholder"
		:disabled="disabled"
		:search="searchContacts"
		:filter-fields="['label', 'phone_number', 'reference']"
		@update:model-value="$emit('update:modelValue', $event)"
		@change="$emit('change', $event)"
	/>
</template>
