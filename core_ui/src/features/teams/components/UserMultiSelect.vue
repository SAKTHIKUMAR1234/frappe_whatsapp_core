<script setup>
	import { computed } from 'vue'
	import MultiLinkField from '@/components/form/MultiLinkField.vue'
	import { call } from '@/services/frappe'

	const props = defineProps({
		modelValue: { type: Array, default: () => [] },
		options: { type: Array, default: () => [] },
	})
	defineEmits(['update:modelValue', 'change'])

	function present(rows) {
		return (rows || []).map((row) => ({
			...row,
			label: row.label || row.full_name || row.name,
			description: row.full_name && row.full_name !== row.name ? row.name : '',
		}))
	}
	const presentedOptions = computed(() => present(props.options))
	async function searchUsers(search) {
		return present(
			await call('frappe_whatsapp_core.workspace_api.search_team_users', {
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
		option-value="name"
		placeholder="Search and select Frappe users"
		:search="searchUsers"
		:filter-fields="['label', 'name', 'full_name']"
		:max-selected-labels="4"
		@update:model-value="$emit('update:modelValue', $event)"
		@change="$emit('change', $event)"
	/>
</template>
