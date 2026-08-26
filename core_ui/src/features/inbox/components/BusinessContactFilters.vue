<script setup>
	import { computed, ref } from 'vue'
	import Button from 'primevue/button'
	import InputNumber from 'primevue/inputnumber'
	import InputText from 'primevue/inputtext'
	import Popover from 'primevue/popover'
	import Select from 'primevue/select'
	import ToggleSwitch from 'primevue/toggleswitch'
	import { ListFilter, RotateCcw, X } from 'lucide-vue-next'

	import MultiLinkField from '@/components/form/MultiLinkField.vue'
	import { call } from '@/services/frappe'

	const props = defineProps({
		schemas: { type: Array, default: () => [] },
		source: { type: String, default: '' },
		filters: { type: Object, default: () => ({}) },
	})
	const emit = defineEmits(['update:source', 'update:filters'])
	const popover = ref(null)
	const open = ref(false)
	const selectedSchema = computed(
		() => props.schemas.find((schema) => schema.name === props.source) || null,
	)
	const activeFilterCount = computed(
		() => Object.values(props.filters || {}).filter(hasValue).length,
	)
	const activeCount = computed(() => activeFilterCount.value + (props.source ? 1 : 0))

	function hasValue(value) {
		if (Array.isArray(value)) return value.length > 0
		return value !== null && value !== undefined && value !== '' && value !== false
	}

	function toggle(event) {
		popover.value?.toggle(event)
	}

	function changeSource(value) {
		emit('update:source', value || '')
		emit('update:filters', {})
	}

	function updateField(fieldname, value) {
		const updated = { ...(props.filters || {}) }
		if (hasValue(value)) updated[fieldname] = value
		else delete updated[fieldname]
		emit('update:filters', updated)
	}

	function clearField(fieldname) {
		updateField(fieldname, null)
	}

	function clearAll() {
		emit('update:source', '')
		emit('update:filters', {})
	}

	function optionsFor(field) {
		return field.control === 'choices' ? field.choices || [] : []
	}

	async function searchFieldOptions(field, search) {
		if (!props.source) return []
		return call('frappe_whatsapp_core.inbox.business_filter_options', {
			source: props.source,
			field: field.fieldname,
			search,
		})
	}

	function dateInputType(field) {
		if (field.fieldtype === 'Datetime') return 'datetime-local'
		if (field.fieldtype === 'Time') return 'time'
		return 'date'
	}
</script>

<template>
	<div v-if="schemas.length" class="business-filter-trigger">
		<Button
			text
			class="filter-button"
			:aria-label="`Filter by business records${activeCount ? `, ${activeCount} active` : ''}`"
			aria-haspopup="dialog"
			:aria-expanded="open"
			@click="toggle"
		>
			<ListFilter :size="15" aria-hidden="true" />
			<span>Business filters</span>
			<strong v-if="activeCount" aria-hidden="true">{{ activeCount }}</strong>
		</Button>
		<Popover
			ref="popover"
			class="business-filter-popover"
			@show="open = true"
			@hide="open = false"
		>
			<section class="business-filter-panel" aria-label="Business record filters">
				<header>
					<strong>Business filters</strong>
					<Button
						v-if="activeCount"
						text
						size="small"
						aria-label="Clear all business filters"
						@click="clearAll"
					>
						<RotateCcw :size="14" />
						<span>Reset</span>
					</Button>
				</header>
				<label class="filter-control">
					<span>Contact source</span>
					<Select
						:model-value="source"
						:options="schemas"
						option-label="display_name"
						option-value="name"
						placeholder="Choose a business record type"
						show-clear
						fluid
						@update:model-value="changeSource"
					/>
				</label>
				<div v-if="selectedSchema" class="filter-fields">
					<label
						v-for="field in selectedSchema.fields"
						:key="field.fieldname"
						class="filter-control"
					>
						<span class="filter-label">
							<span>{{ field.label }}</span>
							<Button
								v-if="hasValue(filters[field.fieldname])"
								text
								rounded
								severity="secondary"
								:aria-label="`Clear ${field.label} filter`"
								@click.prevent="clearField(field.fieldname)"
							>
								<X :size="13" />
							</Button>
						</span>
						<span v-if="field.control === 'boolean'" class="boolean-filter">
							<ToggleSwitch
								:model-value="Boolean(filters[field.fieldname])"
								@update:model-value="updateField(field.fieldname, $event)"
							/>
							<span>Only enabled records</span>
						</span>
						<MultiLinkField
							v-else-if="field.control === 'choices'"
							:model-value="filters[field.fieldname] || []"
							:options="optionsFor(field)"
							:placeholder="`Select ${field.label.toLowerCase()}`"
							@update:model-value="updateField(field.fieldname, $event)"
						/>
						<MultiLinkField
							v-else-if="field.control === 'link'"
							:model-value="filters[field.fieldname] || []"
							:options="[]"
							:search="(query) => searchFieldOptions(field, query)"
							:placeholder="`Search ${field.label.toLowerCase()}`"
							@update:model-value="updateField(field.fieldname, $event)"
						/>
						<InputText
							v-else-if="field.control === 'date'"
							:model-value="filters[field.fieldname] || ''"
							:type="dateInputType(field)"
							fluid
							@update:model-value="updateField(field.fieldname, $event)"
						/>
						<InputNumber
							v-else-if="field.control === 'number'"
							:model-value="filters[field.fieldname] ?? null"
							fluid
							@update:model-value="updateField(field.fieldname, $event)"
						/>
						<InputText
							v-else
							:model-value="filters[field.fieldname] || ''"
							:placeholder="`Contains ${field.label.toLowerCase()}`"
							fluid
							@update:model-value="updateField(field.fieldname, $event)"
						/>
					</label>
				</div>
			</section>
		</Popover>
	</div>
</template>

<style scoped>
	.business-filter-trigger {
		min-width: 0;
	}
	.filter-button {
		width: 100%;
		min-height: 34px;
		justify-content: flex-start;
		gap: 8px;
		padding-inline: 10px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.filter-button strong {
		min-width: 20px;
		height: 20px;
		margin-left: auto;
		display: inline-grid;
		place-items: center;
		border-radius: 999px;
		background: var(--wa-primary-soft);
		color: var(--wa-primary-strong);
		font-size: 11px;
	}
	:global(.business-filter-popover.p-popover) {
		border: 1px solid var(--wa-border);
		background: var(--wa-surface);
		box-shadow: 0 16px 42px rgba(11, 20, 26, 0.2);
	}
	:global(.business-filter-popover .p-popover-content) {
		padding: 0;
	}
	.business-filter-panel {
		width: min(360px, calc(100vw - 24px));
		max-height: min(640px, calc(100vh - 32px));
		display: grid;
		gap: 14px;
		padding: 14px;
		overflow-y: auto;
		color: var(--wa-text);
	}
	.business-filter-panel header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
	}
	.filter-control,
	.filter-fields {
		display: grid;
		gap: 6px;
	}
	.filter-fields {
		gap: 13px;
		padding-top: 2px;
	}
	.filter-control > span:first-child {
		font-size: 12px;
		font-weight: 700;
	}
	.filter-label {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.filter-label :deep(.p-button) {
		width: 26px;
		height: 26px;
		padding: 0;
	}
	.boolean-filter {
		min-height: 38px;
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 13px;
		font-weight: 500;
	}
</style>
