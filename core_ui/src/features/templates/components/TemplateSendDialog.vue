<script setup>
	import { computed, reactive, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import AppDialog from '@/components/AppDialog.vue'
	import InputText from 'primevue/inputtext'
	import { Paperclip, Send } from 'lucide-vue-next'
	import TemplateSelect from '@/features/templates/components/TemplateSelect.vue'
	import { call, errorMessage, uploadFile } from '@/services/frappe'

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
		conversation: { type: String, default: '' },
	})
	const emit = defineEmits(['update:visible', 'send'])
	const selected = ref('')
	const values = reactive({})
	const validationError = ref('')
	const uploadingKey = ref('')
	const uploadedMedia = reactive({})
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
		for (const key of Object.keys(uploadedMedia)) delete uploadedMedia[key]
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

	function mediaAccept(type) {
		return (
			{
				document: '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt',
				image: 'image/*',
				video: 'video/*',
			}[type] || '*/*'
		)
	}

	async function uploadTemplateMedia(descriptor, event) {
		const file = event.target.files?.[0]
		if (!file || !props.conversation) return
		uploadingKey.value = descriptor.key
		validationError.value = ''
		try {
			const stored = await uploadFile(file, true)
			const uploaded = await call('frappe_whatsapp_core.outbound.upload_media', {
				conversation_name: props.conversation,
				file_url: stored.file_url,
				media_type: descriptor.parameterType,
			})
			values[descriptor.key] = uploaded.media_id
			uploadedMedia[descriptor.key] = {
				file_url: uploaded.file_url,
				filename: uploaded.filename || file.name,
			}
		} catch (error) {
			values[descriptor.key] = ''
			delete uploadedMedia[descriptor.key]
			validationError.value = errorMessage(error, 'Unable to upload template media.')
		} finally {
			uploadingKey.value = ''
			event.target.value = ''
		}
	}

	function submit() {
		if (!template.value) return
		try {
			validationError.value = ''
			emit('send', {
				template: template.value.name,
				language_code: template.value.language_code || 'en',
				components: buildTemplateComponents(descriptors.value, values),
				local_file_url:
					Object.values(uploadedMedia).find((item) => item?.file_url)?.file_url || '',
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
			<div v-for="descriptor in descriptors" :key="descriptor.key" class="parameter-field">
				<span>{{ descriptor.label }}</span>
				<div v-if="descriptor.kind === 'media'" class="media-picker">
					<label :for="`template-media-${descriptor.key}`" class="media-button">
						<Paperclip :size="16" />
						{{
							uploadingKey === descriptor.key
								? 'Uploading…'
								: uploadedMedia[descriptor.key]?.filename || 'Choose file'
						}}
					</label>
					<input
						:id="`template-media-${descriptor.key}`"
						type="file"
						:accept="mediaAccept(descriptor.parameterType)"
						:disabled="uploadingKey !== ''"
						@change="uploadTemplateMedia(descriptor, $event)"
					/>
				</div>
				<InputText
					v-else
					v-model="values[descriptor.key]"
					:placeholder="descriptor.example || descriptor.label"
					fluid
				/>
			</div>
			<section v-if="template" class="template-preview">
				<small>{{ template.template_name }} · {{ template.language_code }}</small>
				<p>{{ preview || 'This template has no body preview.' }}</p>
			</section>
			<p v-if="validationError" class="validation-error">{{ validationError }}</p>
		</div>
		<template #footer>
			<Button label="Cancel" text @click="$emit('update:visible', false)" />
			<Button
				label="Send template"
				:loading="loading"
				:disabled="!selected || uploadingKey !== ''"
				@click="submit"
			>
				<template #icon><Send :size="16" /></template>
			</Button>
		</template>
	</AppDialog>
</template>

<style scoped>
	.template-form,
	.template-form label,
	.parameter-field {
		display: grid;
		gap: 8px;
	}
	.template-form {
		gap: 15px;
	}
	.template-form label > span,
	.parameter-field > span {
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
	.media-picker {
		display: grid;
		gap: 6px;
	}
	.media-picker > input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
		pointer-events: none;
	}
	.media-button {
		min-height: 42px;
		padding: 9px 12px;
		display: flex !important;
		align-items: center;
		gap: 8px !important;
		border: 1px solid var(--wa-border);
		border-radius: 9px;
		background: var(--wa-surface);
		cursor: pointer;
	}
	.media-picker small {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.validation-error {
		margin: 0;
		color: var(--wa-danger);
		font-size: 12px;
	}
</style>
