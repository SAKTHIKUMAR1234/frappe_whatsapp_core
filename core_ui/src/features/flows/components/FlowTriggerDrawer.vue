<script setup>
	import Button from 'primevue/button'
	import Drawer from 'primevue/drawer'
	import InputNumber from 'primevue/inputnumber'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'

	const triggerTypes = [
		{ label: 'Chat command', value: 'command' },
		{ label: 'Template / interactive button', value: 'template_button' },
		{ label: 'Inbound text pattern', value: 'inbound_pattern' },
		{ label: 'Case event', value: 'case_event' },
		{ label: 'Schedule', value: 'schedule' },
		{ label: 'API', value: 'api' },
	]

	defineProps({
		visible: Boolean,
		triggers: {
			type: Array,
			required: true,
		},
	})

	const emit = defineEmits(['update:visible', 'add', 'remove'])
</script>

<template>
	<Drawer
		:visible="visible"
		header="Flow triggers"
		position="right"
		:style="{ width: '420px' }"
		@update:visible="emit('update:visible', $event)"
	>
		<p class="drawer-copy">Choose exactly how this flow starts.</p>

		<div v-for="(trigger, index) in triggers" :key="trigger.key" class="trigger-card">
			<div class="trigger-heading">
				<strong>{{ trigger.key }}</strong>
				<Tag :value="trigger.type" severity="secondary" rounded />
			</div>

			<label>Trigger key</label>
			<InputText v-model="trigger.key" fluid />

			<label>Trigger type</label>
			<Select
				v-model="trigger.type"
				:options="triggerTypes"
				option-label="label"
				option-value="value"
				fluid
			/>

			<label>Match value or pattern</label>
			<InputText v-model="trigger.match" fluid />

			<label>Priority</label>
			<InputNumber v-model="trigger.priority" :min="1" :max="10000" fluid />

			<Button
				class="remove-trigger"
				icon="pi pi-trash"
				severity="danger"
				text
				rounded
				@click="emit('remove', index)"
			/>
		</div>

		<Button label="Add trigger" severity="secondary" outlined fluid @click="emit('add')" />
	</Drawer>
</template>

<style scoped>
	.drawer-copy {
		color: var(--wa-muted);
		font-size: 11px;
		line-height: 1.6;
	}

	.trigger-card {
		position: relative;
		padding: 14px;
		margin: 12px 0;
		border: 1px solid var(--wa-border);
		border-radius: 12px;
	}

	.trigger-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.trigger-heading strong {
		font-size: 11px;
	}

	label {
		display: block;
		margin: 13px 0 6px;
		font-size: 12px;
		font-weight: 700;
	}

	.remove-trigger {
		position: absolute;
		right: 6px;
		bottom: 6px;
	}
</style>
