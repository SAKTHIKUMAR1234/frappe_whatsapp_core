<script setup>
	import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
	import AutoComplete from 'primevue/autocomplete'

	defineOptions({ inheritAttrs: false })

	const props = defineProps({
		modelValue: { type: String, default: '' },
		options: { type: Array, default: () => [] },
		optionLabel: { type: String, default: 'label' },
		optionValue: { type: String, default: 'value' },
		placeholder: { type: String, default: 'Search and select' },
		disabled: { type: Boolean, default: false },
		showClear: { type: Boolean, default: true },
		search: { type: Function, default: null },
		searchDebounceMs: { type: Number, default: 250 },
		filterFields: { type: Array, default: () => ['label', 'value', 'description'] },
	})
	const emit = defineEmits(['update:modelValue', 'change'])
	const autocompleteRef = ref(null)
	const query = ref('')
	const suggestions = ref([])
	const selected = ref(null)
	const searching = ref(false)
	const searchError = ref('')
	const focused = ref(false)
	let timer = null
	let sequence = 0
	let blurTimer = null

	function optionValue(option) {
		return option?.[props.optionValue]
	}

	function displayLabel(option) {
		return option?.[props.optionLabel] || optionValue(option) || ''
	}

	function selectedOption(rows = props.options) {
		return (rows || []).find((option) => optionValue(option) === props.modelValue)
	}

	function restoreCommittedValue() {
		const option = selected.value || selectedOption(suggestions.value) || selectedOption()
		query.value = option || props.modelValue || ''
	}

	function localOptions(searchQuery) {
		const normalized = searchQuery.toLocaleLowerCase()
		if (!normalized) return [...props.options]
		const fields = new Set([props.optionLabel, props.optionValue, ...props.filterFields])
		return props.options.filter((option) =>
			[...fields].some((field) =>
				String(option?.[field] || '')
					.toLocaleLowerCase()
					.includes(normalized),
			),
		)
	}

	function complete(event) {
		window.clearTimeout(timer)
		const searchQuery = String(event?.query || '').trim()
		const request = ++sequence
		searchError.value = ''
		if (!props.search) {
			suggestions.value = localOptions(searchQuery)
			return
		}
		searching.value = true
		timer = window.setTimeout(
			async () => {
				try {
					const rows = await props.search(searchQuery)
					if (request === sequence && focused.value) suggestions.value = rows || []
				} catch {
					if (request === sequence)
						searchError.value = 'Search is temporarily unavailable.'
				} finally {
					if (request === sequence) searching.value = false
				}
			},
			searchQuery ? props.searchDebounceMs : 0,
		)
	}

	function selectOption(event) {
		window.clearTimeout(blurTimer)
		selected.value = event.value || null
		query.value = selected.value || ''
		emit('update:modelValue', optionValue(selected.value) || '')
		emit('change', selected.value)
		nextTick(() => focus())
	}

	function updateQuery(value) {
		if (value && typeof value === 'object') {
			selected.value = value
			query.value = value
			return
		}
		if (value == null) {
			if (props.modelValue) restoreCommittedValue()
			else query.value = ''
			return
		}
		query.value = String(value)
	}

	function clear() {
		selected.value = null
		query.value = ''
		emit('update:modelValue', '')
		emit('change', null)
	}

	function open(event) {
		if (props.disabled || autocompleteRef.value?.overlayVisible) return
		const visibleQuery = typeof query.value === 'string' ? query.value : ''
		autocompleteRef.value?.search?.(event, visibleQuery, 'click')
	}

	function optionMouseDown(event, option) {
		if (props.disabled || event.button !== 0) return
		autocompleteRef.value?.onOptionSelect?.(event, option)
		autocompleteRef.value?.hide?.(true)
	}

	function focus() {
		const root = autocompleteRef.value?.$el
		;(root?.querySelector?.('input') || root)?.focus?.()
	}

	function onFocus() {
		window.clearTimeout(blurTimer)
		focused.value = true
	}

	function onBlur() {
		focused.value = false
		sequence += 1
		window.clearTimeout(timer)
		blurTimer = window.setTimeout(() => {
			suggestions.value = []
			searching.value = false
			autocompleteRef.value?.hide?.()
		}, 150)
	}

	watch(
		() => [props.modelValue, props.options],
		() => {
			if (!props.modelValue) {
				selected.value = null
				query.value = ''
				return
			}
			const option = selectedOption(suggestions.value) || selectedOption()
			selected.value = option || null
			query.value = option || props.modelValue
		},
		{ immediate: true, deep: true },
	)

	onBeforeUnmount(() => {
		window.clearTimeout(timer)
		window.clearTimeout(blurTimer)
	})

	defineExpose({ focus })
</script>

<template>
	<AutoComplete
		v-bind="$attrs"
		ref="autocompleteRef"
		:model-value="query"
		:suggestions="suggestions"
		:option-label="props.optionLabel"
		:placeholder="placeholder"
		:disabled="disabled"
		:show-clear="showClear"
		:loading="searching"
		:min-length="0"
		:complete-on-focus="false"
		:auto-option-focus="true"
		force-selection
		fluid
		class="core-link-field"
		@complete="complete"
		@item-select="selectOption"
		@update:model-value="updateQuery"
		@clear="clear"
		@focus="onFocus"
		@click="open"
		@blur="onBlur"
	>
		<template #option="{ option }">
			<div
				class="core-link-field__option"
				@mousedown.left.prevent.stop="optionMouseDown($event, option)"
				@click.prevent.stop
			>
				<strong>{{ displayLabel(option) }}</strong>
				<small v-if="option.description">{{ option.description }}</small>
			</div>
		</template>
		<template #empty>
			<div class="core-link-field__empty">
				{{ searchError || 'No matching records.' }}
			</div>
		</template>
	</AutoComplete>
</template>

<style scoped>
	.core-link-field {
		width: 100%;
		min-width: 0;
	}
	.core-link-field :deep(input) {
		width: 100%;
	}
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
