<script setup>
	import { computed } from 'vue'
	import Button from 'primevue/button'
	import InputText from 'primevue/inputtext'
	import InputNumber from 'primevue/inputnumber'
	import LinkField from '@/components/form/LinkField.vue'
	import MultiLinkField from '@/components/form/MultiLinkField.vue'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import ToggleSwitch from 'primevue/toggleswitch'
	import { Settings2, Trash2 } from 'lucide-vue-next'
	import TemplateSelect from '@/features/templates/components/TemplateSelect.vue'

	const props = defineProps({
		selectedNode: Object,
		selectedEdge: Object,
		choiceOptionsText: String,
		actions: {
			type: Array,
			default: () => [],
		},
		templates: {
			type: Array,
			default: () => [],
		},
		metaFlows: {
			type: Array,
			default: () => [],
		},
	})

	defineEmits(['update:choice-options-text', 'delete', 'ensure-condition'])

	const actionOptions = computed(() =>
		props.actions.map((action) => ({
			...action,
			optionLabel: action.label || action.key,
			optionValue: action.method || action.key,
		})),
	)
	const selectedAction = computed(() => {
		const reference = props.selectedNode?.data?.config?.action
		return props.actions.find(
			(action) => reference === action.key || reference === action.method,
		)
	})
	const actionParameters = computed(() => {
		const schema = selectedAction.value?.parameters || {}
		const required = new Set(schema.required || [])
		return Object.entries(schema.properties || {}).map(([name, property]) => ({
			name,
			title: property.title || name.replaceAll('_', ' '),
			type: property.type || 'string',
			required: required.has(name),
		}))
	})
	const metaFlowOptions = computed(() =>
		props.metaFlows.map((flow) => ({
			label: `${flow.name || flow.id}${flow.status ? ` · ${flow.status}` : ''}`,
			value: String(flow.id),
		})),
	)
	const inputTypes = [
		{ label: 'Text', value: 'text' },
		{ label: 'Number', value: 'number' },
		{ label: 'Radio buttons', value: 'radio' },
		{ label: 'Select list', value: 'select' },
		{ label: 'Multiple selections', value: 'multi_select' },
		{ label: 'Attachment', value: 'attachment' },
		{ label: 'Message or attachment', value: 'content' },
	]
	const mediaTypes = ['image', 'document', 'audio', 'video', 'sticker']
	const isChoiceInput = computed(
		() =>
			['ask_choice'].includes(props.selectedNode?.data?.type) ||
			(props.selectedNode?.data?.type === 'ask_input' &&
				['radio', 'select', 'multi_select'].includes(
					props.selectedNode?.data?.config?.input_type,
				)),
	)

	function prepareAction(action) {
		const config = props.selectedNode.data.config
		config.action = action
		const definition = props.actions.find(
			(item) => item.method === action || item.key === action,
		)
		const previous = config.input || {}
		config.input = {}
		for (const [name, property] of Object.entries(definition?.parameters?.properties || {})) {
			config.input[name] = previous[name] ?? (property.type === 'boolean' ? false : '')
		}
	}
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
				v-if="
					['send_message', 'ask_text', 'ask_choice', 'ask_input', 'end'].includes(
						selectedNode.data.type,
					)
				"
			>
				<label>Message</label>
				<Textarea v-model="selectedNode.data.config.message" rows="4" fluid />
			</template>

			<template v-if="selectedNode.data.type === 'send_template'">
				<label>Available template</label>
				<TemplateSelect
					v-model="selectedNode.data.config.template"
					:options="templates"
					placeholder="Select assigned template"
				/>
				<label>Language code</label>
				<InputText v-model="selectedNode.data.config.language" placeholder="en" fluid />
			</template>

			<template v-if="selectedNode.data.type === 'send_flow'">
				<label>Published Meta Flow</label>
				<LinkField
					v-model="selectedNode.data.config.flow_id"
					:options="metaFlowOptions"
					option-label="label"
					option-value="value"
					placeholder="Select a Flow"
				/>
				<label>Message</label>
				<Textarea v-model="selectedNode.data.config.message" rows="3" fluid />
				<label>Button label</label>
				<InputText v-model="selectedNode.data.config.flow_cta" fluid />
				<label>Opening action</label>
				<Select
					v-model="selectedNode.data.config.flow_action"
					:options="['navigate', 'data_exchange']"
					fluid
				/>
				<template v-if="selectedNode.data.config.flow_action === 'navigate'">
					<label>First screen</label>
					<InputText v-model="selectedNode.data.config.screen" fluid />
				</template>
				<label>Save response as</label>
				<InputText v-model="selectedNode.data.config.response_key" fluid />
			</template>

			<template
				v-if="['ask_text', 'ask_choice', 'ask_input'].includes(selectedNode.data.type)"
			>
				<template v-if="selectedNode.data.type === 'ask_input'">
					<label>Input type</label>
					<Select
						v-model="selectedNode.data.config.input_type"
						:options="inputTypes"
						option-label="label"
						option-value="value"
						fluid
					/>
				</template>
				<label>Save answer as</label>
				<InputText
					v-model="selectedNode.data.config.answer_key"
					placeholder="customer_answer"
					fluid
				/>
			</template>

			<template v-if="selectedNode.data.type === 'ask_input'">
				<div class="toggle-row compact-toggle">
					<div>
						<strong>Required response</strong>
						<small>Do not continue with an empty value</small>
					</div>
					<ToggleSwitch v-model="selectedNode.data.config.required" />
				</div>
				<label>Invalid response message</label>
				<InputText
					v-model="selectedNode.data.config.validation_message"
					placeholder="Please send a valid response."
					fluid
				/>
			</template>

			<template v-if="isChoiceInput">
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
				<label>List button label</label>
				<InputText
					v-model="selectedNode.data.config.button_label"
					placeholder="Choose"
					fluid
				/>
				<p
					v-if="selectedNode.data.config.input_type === 'multi_select'"
					class="field-note"
				>
					Customers may reply with option numbers, labels, or values separated by commas.
				</p>
				<label>
					Dynamic options source
					<small>Optional action result path</small>
				</label>
				<InputText
					v-model="selectedNode.data.config.options_from"
					placeholder="{{actions.catalog.options}}"
					fluid
				/>
			</template>

			<template
				v-if="
					selectedNode.data.type === 'ask_input' &&
					selectedNode.data.config.input_type === 'number'
				"
			>
				<label>Minimum</label>
				<InputNumber v-model="selectedNode.data.config.minimum" fluid />
				<label>Maximum</label>
				<InputNumber v-model="selectedNode.data.config.maximum" fluid />
				<div class="toggle-row compact-toggle">
					<div>
						<strong>Whole numbers only</strong>
						<small>Reject decimal values</small>
					</div>
					<ToggleSwitch v-model="selectedNode.data.config.integer_only" />
				</div>
			</template>

			<template
				v-if="
					selectedNode.data.type === 'ask_input' &&
					['attachment', 'content'].includes(selectedNode.data.config.input_type)
				"
			>
				<label>Accepted attachments</label>
				<MultiLinkField
					v-model="selectedNode.data.config.accepted_media_types"
					:options="mediaTypes"
					display="chip"
					fluid
				/>
				<p class="field-note">
					The inbound file is stored as a private Frappe File before the next action
					runs. Message-or-attachment inputs can also show action buttons while
					accepting free text and media.
				</p>
			</template>

			<template v-if="selectedNode.data.type === 'action'">
				<label>Python action</label>
				<Select
					:model-value="selectedAction?.method || selectedNode.data.config.action"
					:options="actionOptions"
					option-label="optionLabel"
					option-value="optionValue"
					filter
					fluid
					@update:model-value="prepareAction"
				/>
				<code v-if="selectedAction" class="action-path">{{ selectedAction.method }}</code>
				<template v-for="parameter in actionParameters" :key="parameter.name">
					<label>
						{{ parameter.title }}
						<small v-if="parameter.required">Required</small>
					</label>
					<ToggleSwitch
						v-if="parameter.type === 'boolean'"
						v-model="selectedNode.data.config.input[parameter.name]"
					/>
					<Textarea
						v-else-if="parameter.name === 'description'"
						v-model="selectedNode.data.config.input[parameter.name]"
						rows="3"
						fluid
					/>
					<InputText
						v-else
						v-model="selectedNode.data.config.input[parameter.name]"
						:placeholder="
							parameter.type === 'object' ? '{{responses.form_response}}' : ''
						"
						fluid
					/>
				</template>
				<label>Save action result as</label>
				<InputText
					v-model="selectedNode.data.config.output_key"
					placeholder="action_result"
					fluid
				/>
			</template>

			<template v-if="selectedNode.data.type === 'wait'">
				<label>Resume on</label>
				<InputText v-model="selectedNode.data.config.resume_on" fluid />
			</template>

			<template v-if="selectedNode.data.type === 'human_handoff'">
				<label>Handoff reason</label>
				<Textarea v-model="selectedNode.data.config.reason" rows="3" fluid />
				<label>Customer message</label>
				<Textarea v-model="selectedNode.data.config.message" rows="3" fluid />
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
		</div>
	</aside>
</template>

<style scoped>
	.flow-inspector {
		padding: 15px;
		overflow-y: auto;
		border-left: 1px solid var(--wa-border);
		background: var(--wa-surface);
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
		color: var(--wa-muted);
		font-size: 12px;
		text-transform: capitalize;
	}

	label {
		display: flex;
		justify-content: space-between;
		margin: 15px 0 6px;
		font-size: 12px;
		font-weight: 750;
	}

	label small {
		color: var(--wa-muted);
		font-weight: 500;
	}

	.field-note {
		margin-top: 7px;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.5;
	}

	.action-path {
		display: block;
		padding: 8px 9px;
		margin-top: 8px;
		overflow-wrap: anywhere;
		border: 1px solid var(--wa-border);
		border-radius: 7px;
		color: var(--wa-muted);
		background: var(--wa-surface-muted);
		font-size: 11px;
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
		font-size: 12px;
	}

	.toggle-row small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.empty-inspector {
		height: 100%;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		color: var(--wa-muted);
		text-align: center;
	}

	.empty-inspector strong {
		margin-top: 12px;
		color: var(--wa-text);
		font-size: 11px;
	}
</style>
