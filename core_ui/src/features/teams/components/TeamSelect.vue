<script setup>
	import LinkField from '@/components/form/LinkField.vue'
	import { call } from '@/services/frappe'

	defineProps({
		modelValue: { type: String, default: '' },
		placeholder: { type: String, default: 'Search teams' },
	})
	defineEmits(['update:modelValue', 'change'])

	async function searchTeams(search) {
		return call('frappe_whatsapp_core.workspace_api.search_team_options', {
			search,
			limit: 50,
		})
	}
</script>

<template>
	<LinkField
		:model-value="modelValue"
		:options="[]"
		option-label="team_name"
		option-value="name"
		:placeholder="placeholder"
		:show-clear="true"
		:search="searchTeams"
		:filter-fields="['team_name', 'name', 'description']"
		@update:model-value="$emit('update:modelValue', $event || '')"
		@change="$emit('change', $event)"
	/>
</template>
