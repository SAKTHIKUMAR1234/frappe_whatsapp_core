<script setup>
	import Button from 'primevue/button'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import ToggleSwitch from 'primevue/toggleswitch'
	import { Settings2, Trash2 } from 'lucide-vue-next'

	defineProps({
		selectedNode: Object,
		selectedEdge: Object,
		choiceOptionsText: String,
	})

	defineEmits(['update:choice-options-text', 'delete', 'ensure-condition'])
</script>

<template>
	<aside class="flow-inspector">
		<template v-if="selectedNode">
			<div class="panel-heading">
				<span>Node settings</span>
				<small>{{ selectedNode.data.type.replaceAll('_', ' ') }}</small>
			</div>

			<label>Label</label>
			<InputText v-model="selectedNode.data.config.label" fluid />

			<template
				v-if="['send_message', 'ask_text', 'ask_choice'].includes(selectedNode.data.type)"
			>
				<label>Message</label>
				<Textarea v-model="selectedNode.data.config.message" rows="4" fluid />
			</template>

			<template v-if="selectedNode.data.type === 'send_template'">
				<label>Available template</label>
				<Select
					v-model="selectedNode.data.config.template"
					:options="[]"
					placeholder="Select assigned template"
					fluid
				/>
				<div class="field-note">Read-only catalog from the Integration app.</div>
			</template>

			<template v-if="['ask_text', 'ask_choice'].includes(selectedNode.data.type)">
				<label>Save answer as</label>
				<InputText
					v-model="selectedNode.data.config.answer_key"
					placeholder="customer_answer"
					fluid
				/>
			</template>

			<template v-if="selectedNode.data.type === 'ask_choice'">
				<label>
					Options
					<small>Label|value, one per line</small>
				</label>
				<Textarea
					:model-value="choiceOptionsText"
					rows="5"
					fluid
					@update:model-value="$emit('update:choice-options-text', $event)"
				/>
			</template>

			<template v-if="selectedNode.data.type === 'action'">
				<label>Registered action</label>
				<Select
					v-model="selectedNode.data.config.action"
					:options="['context.set', 'case.create']"
					fluid
				/>
				<div class="field-note">
					Only typed actions registered by Core or a solution app can appear.
				</div>
			</template>

			<template v-if="selectedNode.data.type === 'wait'">
				<label>Resume on</label>
				<InputText v-model="selectedNode.data.config.resume_on" fluid />
			</template>

			<template v-if="selectedNode.data.type === 'human_handoff'">
				<label>Handoff reason</label>
				<Textarea v-model="selectedNode.data.config.reason" rows="3" fluid />
			</template>

			<Button
				class="delete-button"
				label="Delete node"
				severity="danger"
				text
				fluid
				@click="$emit('delete')"
			>
				<template #icon><Trash2 :size="14" /></template>
			</Button>
		</template>

		<template v-else-if="selectedEdge">
			<div class="panel-heading">
				<span>Branch settings</span>
				<small>{{ selectedEdge.source }} → {{ selectedEdge.target }}</small>
			</div>

			<div class="toggle-row">
				<div>
					<strong>Default branch</strong>
					<small>Use when no condition matches</small>
				</div>
				<ToggleSwitch v-model="selectedEdge.data.default" />
			</div>

			<Button
				label="Add condition"
				severity="secondary"
				outlined
				fluid
				@click="$emit('ensure-condition')"
			/>

			<template v-if="selectedEdge.data.when">
				<label>Context variable</label>
				<InputText v-model="selectedEdge.data.when.left.var" fluid />

				<label>Operator</label>
				<Select
					v-model="selectedEdge.data.when.op"
					:options="['eq', 'ne', 'contains', 'in', 'exists', 'gt', 'gte', 'lt', 'lte']"
					fluid
				/>

				<label>Expected value</label>
				<InputText v-model="selectedEdge.data.when.right" fluid />
			</template>

			<label>
				Maximum traversals
				<small>Only for loops</small>
			</label>
			<InputText v-model="selectedEdge.data.max_traversals" type="number" fluid />

			<Button
				class="delete-button"
				label="Delete connection"
				severity="danger"
				text
				fluid
				@click="$emit('delete')"
			>
				<template #icon><Trash2 :size="14" /></template>
			</Button>
		</template>

		<div v-else class="empty-inspector">
			<Settings2 :size="28" />
			<strong>Select a node or branch</strong>
			<p>Every option is configured using safe fields—no Python, SQL or shell commands.</p>
		</div>
	</aside>
</template>

<style scoped>
	.flow-inspector {
		padding: 15px;
		overflow-y: auto;
		border-left: 1px solid var(--wa-border);
		background: white;
	}

	.panel-heading {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 13px;
	}

	.panel-heading span {
		font-size: 11px;
		font-weight: 800;
	}

	.panel-heading small {
		color: #87948e;
		font-size: 8px;
		text-transform: capitalize;
	}

	label {
		display: flex;
		justify-content: space-between;
		margin: 15px 0 6px;
		font-size: 9px;
		font-weight: 750;
	}

	label small {
		color: #8b9791;
		font-weight: 500;
	}

	.field-note {
		margin-top: 7px;
		color: #829088;
		font-size: 8px;
		line-height: 1.5;
	}

	.delete-button {
		margin-top: 24px;
	}

	.toggle-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 12px 0;
		margin-bottom: 10px;
		border-bottom: 1px solid var(--wa-border);
	}

	.toggle-row strong,
	.toggle-row small {
		display: block;
	}

	.toggle-row strong {
		font-size: 10px;
	}

	.toggle-row small {
		margin-top: 3px;
		color: #87948e;
		font-size: 8px;
	}

	.empty-inspector {
		height: 100%;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		color: #87948e;
		text-align: center;
	}

	.empty-inspector strong {
		margin-top: 12px;
		color: #36453e;
		font-size: 11px;
	}

	.empty-inspector p {
		max-width: 220px;
		font-size: 9px;
		line-height: 1.6;
	}
</style>
