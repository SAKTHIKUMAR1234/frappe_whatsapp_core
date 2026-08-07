<script setup>
	import { onBeforeUnmount, ref, watch } from 'vue'
	import Select from 'primevue/select'
	import { call } from '@/services/frappe'

	const props = defineProps({
		modelValue: { type: String, default: '' },
		options: { type: Array, default: () => [] },
		placeholder: { type: String, default: 'Select a Core contact' },
		disabled: { type: Boolean, default: false },
		showClear: { type: Boolean, default: true },
	})
	defineEmits(['update:modelValue'])
	const available = ref([...props.options])
	const searching = ref(false)
	const searchError = ref('')
	let searchTimer = null
	let searchSequence = 0

	function selectedOption() {
		return available.value.find((option) => option.identity === props.modelValue)
	}
	function setOptions(rows) {
		const selected = selectedOption()
		available.value = [...(selected ? [selected] : []), ...(rows || [])].filter(
			(option, index, values) =>
				values.findIndex((candidate) => candidate.identity === option.identity) === index,
		)
	}
	function filterContacts(event) {
		window.clearTimeout(searchTimer)
		const search = String(event.value || '').trim()
		if (!search) {
			searchSequence += 1
			searching.value = false
			searchError.value = ''
			setOptions(props.options)
			return
		}
		const request = ++searchSequence
		searching.value = true
		searchError.value = ''
		searchTimer = window.setTimeout(async () => {
			try {
				const rows = await call(
					'frappe_whatsapp_core.frontend_api.search_contact_options',
					{
						search,
						limit: 50,
					},
				)
				if (request === searchSequence) setOptions(rows)
			} catch {
				if (request === searchSequence)
					searchError.value = 'Contact search is unavailable.'
			} finally {
				if (request === searchSequence) searching.value = false
			}
		}, 250)
	}
	watch(
		() => props.options,
		(rows) => setOptions(rows),
		{ deep: true },
	)
	onBeforeUnmount(() => window.clearTimeout(searchTimer))
</script>

<template>
	<Select
		:model-value="modelValue"
		:options="available"
		option-label="label"
		option-value="identity"
		filter
		:loading="searching"
		:filter-fields="['label', 'phone_number', 'reference']"
		:show-clear="showClear"
		:placeholder="placeholder"
		:disabled="disabled"
		class="contact-select"
		@filter="filterContacts"
		@update:model-value="$emit('update:modelValue', $event)"
	>
		<template #value="{ value, placeholder: emptyLabel }">
			<span v-if="!value" class="placeholder">{{ emptyLabel }}</span>
			<template v-else>
				{{ available.find((option) => option.identity === value)?.label || value }}
			</template>
		</template>
		<template #option="{ option }">
			<div class="contact-option">
				<strong>{{ option.label }}</strong>
				<small>{{ option.phone_number }} · {{ option.reference }}</small>
			</div>
		</template>
		<template #empty>
			<div class="empty-option">
				{{ searchError || 'No Core contacts are available.' }}
			</div>
		</template>
	</Select>
</template>

<style scoped>
	.contact-select {
		width: 100%;
		min-width: 0;
	}
	.contact-option strong,
	.contact-option small {
		display: block;
	}
	.contact-option strong {
		font-size: 13px;
	}
	.contact-option small,
	.placeholder,
	.empty-option {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.contact-option small {
		margin-top: 2px;
	}
	.empty-option {
		padding: 10px;
	}
</style>
