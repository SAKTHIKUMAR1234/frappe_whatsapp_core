<script setup>
	import { computed, reactive, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import AppDialog from '@/components/AppDialog.vue'
	import InputText from 'primevue/inputtext'
	import { Send } from 'lucide-vue-next'
	import TemplateSelect from '@/features/templates/components/TemplateSelect.vue'

	import {
		buildTemplateComponents,
		templateParameterDescriptors,
		templatePreview,
	} from '@/features/templates/templateParameters'

	const props = defineProps({
		visible: { type: Boolean, default: false },
		templates: { type: Array, default: () => [] },
		loading: { type: Boolean, default: false },
		initialTemplate: { type: String, default: '' },
	})
	const emit = defineEmits(['update:visible', 'send'])
	const selected = ref('')
	const values = reactive({})
	const validationError = ref('')
	const availableTemplates = computed(() =>
		props.templates.filter(
			(template) => template.enabled !== 0 && template.approval_status !== 'REJECTED',
		),
	)
	const template = computed(() =>
		availableTemplates.value.find((row) => row.name === selected.value),
	)
	const descriptors = computed(() => templateParameterDescriptors(template.value))
	const preview = computed(() => templatePreview(template.value, descriptors.value, values))

	function resetValues() {
		for (const key of Object.keys(values)) delete values[key]
		for (const descriptor of descriptors.value)
			values[descriptor.key] = descriptor.example || ''
		validationError.value = ''
	}

	watch(
		() => props.visible,
		(open) => {
			if (!open) return
			selected.value = props.initialTemplate || availableTemplates.value[0]?.name || ''
			resetValues()
		},
	)
	watch(selected, resetValues)

	function submit() {
		if (!template.value) return
		try {
			validationError.value = ''
			emit('send', {
				template: template.value.name,
				language_code: template.value.language_code || 'en',
				components: buildTemplateComponents(descriptors.value, values),
			})
		} catch (error) {
			validationError.value = error?.message || 'Complete the required template values.'
		}
	}
</script>

<template>
	<AppDialog
		:visible="visible"
		modal
		header="Send approved template"
		:style="{ width: '560px', maxWidth: '94vw' }"
		@update:visible="$emit('update:visible', $event)"
	>
		<div class="template-form">
			<label>
				<span>Template</span>
				<TemplateSelect v-model="selected" :options="availableTemplates" />
			</label>
			<label v-for="descriptor in descriptors" :key="descriptor.key">
				<span>{{ descriptor.label }}</span>
				<InputText
					v-model="values[descriptor.key]"
					:placeholder="descriptor.example || descriptor.label"
					fluid
				/>
			</label>
			<section v-if="template" class="template-preview">
				<small>{{ template.template_name }} · {{ template.language_code }}</small>
				<p>{{ preview || 'This template has no body preview.' }}</p>
			</section>
			<p v-if="validationError" class="validation-error">{{ validationError }}</p>
		</div>
		<template #footer>
			<Button label="Cancel" text @click="$emit('update:visible', false)" />
			<Button label="Send template" :loading="loading" :disabled="!selected" @click="submit">
				<template #icon><Send :size="16" /></template>
			</Button>
		</template>
	</AppDialog>
</template>

<style scoped>
	.template-form,
	.template-form label {
		display: grid;
		gap: 8px;
	}
	.template-form {
		gap: 15px;
	}
	.template-form label > span {
		font-size: 12px;
		font-weight: 700;
	}
	.template-preview {
		padding: 14px;
		border: 1px solid var(--wa-border);
		border-radius: 12px;
		background: var(--wa-surface-muted);
	}
	.template-preview small {
		color: var(--wa-muted);
		font-size: 11px;
		font-weight: 700;
	}
	.template-preview p {
		margin: 8px 0 0;
		white-space: pre-wrap;
		line-height: 1.5;
	}
	.validation-error {
		margin: 0;
		color: var(--wa-danger);
		font-size: 12px;
	}
</style>
