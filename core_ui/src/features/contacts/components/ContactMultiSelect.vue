<script setup>
	import { onBeforeUnmount, ref, watch } from 'vue'
	import MultiSelect from 'primevue/multiselect'
	import { call } from '@/services/frappe'

	const props = defineProps({
		modelValue: { type: Array, default: () => [] },
		options: { type: Array, default: () => [] },
		placeholder: { type: String, default: 'Search and select Core contacts' },
		disabled: { type: Boolean, default: false },
	})
	defineEmits(['update:modelValue'])
	const available = ref([...props.options])
	const searching = ref(false)
	const searchError = ref('')
	let searchTimer = null
	let searchSequence = 0

	function retainSelected(rows) {
		const selected = available.value.filter((option) =>
			props.modelValue.includes(option.identity),
		)
		available.value = [...selected, ...(rows || [])].filter(
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
			retainSelected(props.options)
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
				if (request === searchSequence) retainSelected(rows)
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
		(rows) => retainSelected(rows),
		{ deep: true },
	)
	onBeforeUnmount(() => window.clearTimeout(searchTimer))
</script>

<template>
	<MultiSelect
		:model-value="modelValue"
		:options="available"
		option-value="identity"
		filter
		display="chip"
		:loading="searching"
		:filter-fields="['label', 'phone_number', 'reference']"
		:placeholder="placeholder"
		:disabled="disabled"
		:max-selected-labels="8"
		fluid
		@filter="filterContacts"
		@update:model-value="$emit('update:modelValue', $event)"
	>
		<template #option="{ option }">
			<div class="contact-option">
				<strong>{{ option.label }}</strong>
				<small>{{ option.phone_number }} · {{ option.reference }}</small>
			</div>
		</template>
		<template #empty>
			<div class="empty-option">{{ searchError || 'No matching Core contacts.' }}</div>
		</template>
	</MultiSelect>
</template>

<style scoped>
	.contact-option strong,
	.contact-option small {
		display: block;
	}
	.contact-option strong {
		font-size: 13px;
	}
	.contact-option small,
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
