<script setup>
	import Button from 'primevue/button'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'

	const props = defineProps({
		modelValue: { type: Array, default: () => [] },
	})
	const emit = defineEmits(['update:modelValue'])
	const phoneTypes = ['CELL', 'MAIN', 'HOME', 'WORK', 'IPHONE']
	const emailTypes = ['WORK', 'HOME']

	function blankContact() {
		return {
			formatted_name: '',
			first_name: '',
			last_name: '',
			phone: '',
			phone_type: 'CELL',
			email: '',
			email_type: 'WORK',
			company: '',
			title: '',
		}
	}
	function update(index, field, value) {
		const contacts = props.modelValue.map((contact, row) =>
			row === index ? { ...contact, [field]: value } : contact,
		)
		emit('update:modelValue', contacts)
	}
	function add() {
		if (props.modelValue.length >= 10) return
		emit('update:modelValue', [...props.modelValue, blankContact()])
	}
	function remove(index) {
		const contacts = props.modelValue.filter((_contact, row) => row !== index)
		emit('update:modelValue', contacts.length ? contacts : [blankContact()])
	}
</script>

<template>
	<div class="contact-editor">
		<article v-for="(contact, index) in modelValue" :key="index" class="contact-card">
			<header>
				<strong>Contact {{ index + 1 }}</strong>
				<Button
					v-if="modelValue.length > 1"
					icon="pi pi-trash"
					severity="danger"
					text
					rounded
					aria-label="Remove contact"
					@click="remove(index)"
				/>
			</header>
			<div class="contact-grid">
				<label class="full-row"
					>Display name *<InputText
						:model-value="contact.formatted_name"
						placeholder="Name shown in WhatsApp"
						@update:model-value="update(index, 'formatted_name', $event)"
				/></label>
				<label
					>First name<InputText
						:model-value="contact.first_name"
						@update:model-value="update(index, 'first_name', $event)"
				/></label>
				<label
					>Last name<InputText
						:model-value="contact.last_name"
						@update:model-value="update(index, 'last_name', $event)"
				/></label>
				<label class="wide-field"
					>Phone *<InputText
						:model-value="contact.phone"
						placeholder="Country code and number"
						@update:model-value="update(index, 'phone', $event)"
				/></label>
				<label
					>Phone type<Select
						:model-value="contact.phone_type"
						:options="phoneTypes"
						@update:model-value="update(index, 'phone_type', $event)"
				/></label>
				<label class="wide-field"
					>Email<InputText
						:model-value="contact.email"
						type="email"
						@update:model-value="update(index, 'email', $event)"
				/></label>
				<label
					>Email type<Select
						:model-value="contact.email_type"
						:options="emailTypes"
						@update:model-value="update(index, 'email_type', $event)"
				/></label>
				<label
					>Company<InputText
						:model-value="contact.company"
						@update:model-value="update(index, 'company', $event)"
				/></label>
				<label
					>Job title<InputText
						:model-value="contact.title"
						@update:model-value="update(index, 'title', $event)"
				/></label>
			</div>
		</article>
		<Button
			label="Add another contact"
			icon="pi pi-plus"
			outlined
			:disabled="modelValue.length >= 10"
			@click="add"
		/>
	</div>
</template>

<style scoped>
	.contact-editor {
		display: grid;
		gap: 12px;
	}
	.contact-card {
		display: grid;
		gap: 10px;
		padding: 12px;
		border: 1px solid var(--wa-border);
		border-radius: 12px;
	}
	.contact-card header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.contact-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
	}
	.contact-grid label {
		display: grid;
		gap: 5px;
		min-width: 0;
		font-size: 12px;
	}
	.full-row {
		grid-column: 1 / -1;
	}
	@media (max-width: 560px) {
		.contact-grid {
			grid-template-columns: 1fr;
		}
		.full-row {
			grid-column: auto;
		}
	}
</style>
