<script setup>
	import Button from 'primevue/button'
	import Drawer from 'primevue/drawer'
	import InputText from 'primevue/inputtext'
	import Tag from 'primevue/tag'

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
		<p class="drawer-copy">
			A published flow can start from a command, template button, inbound pattern, case
			event, schedule or API.
		</p>

		<div v-for="(trigger, index) in triggers" :key="trigger.key" class="trigger-card">
			<div class="trigger-heading">
				<strong>{{ trigger.key }}</strong>
				<Tag :value="trigger.type" severity="secondary" rounded />
			</div>

			<label>Match value</label>
			<InputText v-model="trigger.match" fluid />

			<Button
				class="remove-trigger"
				icon="pi pi-trash"
				severity="danger"
				text
				rounded
				@click="emit('remove', index)"
			/>
		</div>

		<Button
			label="Add command trigger"
			severity="secondary"
			outlined
			fluid
			@click="emit('add')"
		/>
	</Drawer>
</template>

<style scoped>
	.drawer-copy {
		color: #718079;
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
		font-size: 9px;
		font-weight: 700;
	}

	.remove-trigger {
		position: absolute;
		right: 6px;
		bottom: 6px;
	}
</style>
