<script setup>
	import { onBeforeUnmount, ref, watch } from 'vue'
	import MultiSelect from 'primevue/multiselect'
	import { call } from '@/services/frappe'

	const props = defineProps({
		modelValue: { type: Array, default: () => [] },
		options: { type: Array, default: () => [] },
	})
	defineEmits(['update:modelValue'])
	const available = ref([...props.options])
	const searching = ref(false)
	const searchError = ref('')
	let timer = null
	let sequence = 0

	function retainSelected(rows) {
		const selected = available.value.filter((option) => props.modelValue.includes(option.name))
		available.value = [...selected, ...(rows || [])].filter(
			(option, index, values) =>
				values.findIndex((candidate) => candidate.name === option.name) === index,
		)
	}
	function filterUsers(event) {
		window.clearTimeout(timer)
		const search = String(event.value || '').trim()
		if (!search) {
			sequence += 1
			searching.value = false
			searchError.value = ''
			retainSelected(props.options)
			return
		}
		const request = ++sequence
		searching.value = true
		searchError.value = ''
		timer = window.setTimeout(async () => {
			try {
				const rows = await call('frappe_whatsapp_core.workspace_api.search_team_users', {
					search,
					limit: 50,
				})
				if (request === sequence) retainSelected(rows)
			} catch {
				if (request === sequence) searchError.value = 'User search is unavailable.'
			} finally {
				if (request === sequence) searching.value = false
			}
		}, 250)
	}
	watch(
		() => props.options,
		(rows) => retainSelected(rows),
		{ deep: true },
	)
	onBeforeUnmount(() => window.clearTimeout(timer))
</script>

<template>
	<MultiSelect
		:model-value="modelValue"
		:options="available"
		option-label="label"
		option-value="name"
		filter
		display="chip"
		:loading="searching"
		:filter-fields="['label', 'name', 'full_name']"
		:show-toggle-all="false"
		:max-selected-labels="4"
		fluid
		placeholder="Search and select Frappe users"
		@filter="filterUsers"
		@update:model-value="$emit('update:modelValue', $event)"
	>
		<template #option="{ option }">
			<div class="user-option">
				<strong>{{ option.full_name || option.name }}</strong>
				<small>{{ option.name }}</small>
			</div>
		</template>
		<template #empty>
			<div class="empty-option">{{ searchError || 'No matching enabled users.' }}</div>
		</template>
	</MultiSelect>
</template>

<style scoped>
	.user-option {
		display: grid;
		gap: 2px;
		min-width: 0;
	}
	.user-option strong,
	.user-option small {
		overflow-wrap: anywhere;
	}
	.user-option small,
	.empty-option {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.empty-option {
		padding: 10px;
	}
</style>
