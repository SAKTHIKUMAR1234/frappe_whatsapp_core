<script setup>
	import { onBeforeUnmount, ref, watch } from 'vue'
	import MultiSelect from 'primevue/multiselect'

	const props = defineProps({
		modelValue: { type: Array, default: () => [] },
		options: { type: Array, default: () => [] },
		optionLabel: { type: String, default: 'label' },
		optionValue: { type: String, default: 'value' },
		placeholder: { type: String, default: 'Search and select' },
		disabled: { type: Boolean, default: false },
		search: { type: Function, default: null },
		searchDebounceMs: { type: Number, default: 250 },
		filterFields: { type: Array, default: () => ['label', 'value', 'description'] },
		maxSelectedLabels: { type: Number, default: 8 },
	})
	defineEmits(['update:modelValue', 'change'])
	const available = ref([...props.options])
	const searching = ref(false)
	const searchError = ref('')
	let timer = null
	let sequence = 0

	function setOptions(rows) {
		const selected = available.value.filter((option) =>
			props.modelValue.includes(option?.[props.optionValue]),
		)
		available.value = [...selected, ...(rows || [])].filter(
			(option, index, values) =>
				values.findIndex(
					(candidate) => candidate?.[props.optionValue] === option?.[props.optionValue],
				) === index,
		)
	}
	function filterOptions(event) {
		window.clearTimeout(timer)
		const query = String(event.value || '').trim()
		if (!query || !props.search) {
			sequence += 1
			searching.value = false
			searchError.value = ''
			setOptions(props.options)
			return
		}
		const request = ++sequence
		searching.value = true
		searchError.value = ''
		timer = window.setTimeout(async () => {
			try {
				const rows = await props.search(query)
				if (request === sequence) setOptions(rows)
			} catch {
				if (request === sequence) searchError.value = 'Search is temporarily unavailable.'
			} finally {
				if (request === sequence) searching.value = false
			}
		}, props.searchDebounceMs)
	}
	watch(
		() => props.options,
		(rows) => setOptions(rows),
		{ deep: true },
	)
	onBeforeUnmount(() => window.clearTimeout(timer))
</script>

<template>
	<MultiSelect
		:model-value="modelValue"
		:options="available"
		:option-label="optionLabel"
		:option-value="optionValue"
		filter
		display="chip"
		:loading="searching"
		:filter-fields="filterFields"
		:placeholder="placeholder"
		:disabled="disabled"
		:max-selected-labels="maxSelectedLabels"
		fluid
		@filter="filterOptions"
		@update:model-value="$emit('update:modelValue', $event)"
		@change="$emit('change', $event)"
	>
		<template #option="{ option }">
			<div class="core-link-field__option">
				<strong>{{ option[optionLabel] }}</strong>
				<small v-if="option.description">{{ option.description }}</small>
			</div>
		</template>
		<template #empty>
			<div class="core-link-field__empty">{{ searchError || 'No matching records.' }}</div>
		</template>
	</MultiSelect>
</template>

<style scoped>
	.core-link-field__option {
		display: grid;
		min-width: 0;
		gap: 2px;
	}
	.core-link-field__option strong,
	.core-link-field__option small {
		overflow-wrap: anywhere;
	}
	.core-link-field__option small,
	.core-link-field__empty {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.core-link-field__empty {
		padding: 10px;
	}
</style>
