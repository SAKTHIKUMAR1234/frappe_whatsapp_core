<script setup>
	import { computed, reactive, ref, watch } from 'vue'

	import AppDialog from '@/components/AppDialog.vue'
	import { call, errorMessage } from '@/services/frappe'

	const props = defineProps({
		modelValue: { type: Boolean, default: false },
		template: { type: Object, default: null },
	})
	const emit = defineEmits(['update:modelValue', 'saved'])
	const saving = ref(false)
	const submitError = ref('')
	const editing = computed(() => Boolean(props.template?.name))
	const form = reactive({
		template_name: '',
		language_code: 'en',
		category: 'UTILITY',
		header_type: '',
		header_content: '',
		body_text: '',
		footer_text: '',
	})

	function reset() {
		const row = props.template || {}
		Object.assign(form, {
			template_name: row.template_name || '',
			language_code: row.language_code || 'en',
			category: row.category || 'UTILITY',
			header_type: row.header_type || '',
			header_content: row.header_content || '',
			body_text: row.body_text || '',
			footer_text: row.footer_text || '',
		})
		submitError.value = ''
	}

	async function submit() {
		if (!form.template_name.trim() || !form.body_text.trim()) {
			submitError.value = 'Template name and body are required.'
			return
		}
		saving.value = true
		submitError.value = ''
		try {
			const result = await call(
				'frappe_whatsapp_core.template_catalog.request_template_upsert',
				{
					template_key: props.template?.name || null,
					template: { ...form },
				},
			)
			emit('saved', result)
			emit('update:modelValue', false)
		} catch (error) {
			submitError.value = errorMessage(error, 'Unable to submit the template to Meta.')
		} finally {
			saving.value = false
		}
	}

	watch(
		() => [props.modelValue, props.template],
		([visible]) => {
			if (visible) reset()
		},
		{ deep: true },
	)
</script>

<template>
	<AppDialog
		:model-value="modelValue"
		:header="editing ? 'Edit template' : 'Create template'"
		@update:model-value="emit('update:modelValue', $event)"
	>
		<form class="template-editor" @submit.prevent="submit">
			<div class="field-grid">
				<label>
					<span>Template name</span>
					<input
						v-model="form.template_name"
						type="text"
						maxlength="512"
						placeholder="order_update"
						:disabled="editing"
						required
					/>
				</label>
				<label>
					<span>Language</span>
					<input
						v-model="form.language_code"
						type="text"
						maxlength="32"
						placeholder="en"
						:disabled="editing"
						required
					/>
				</label>
				<label>
					<span>Category</span>
					<select v-model="form.category">
						<option value="UTILITY">Utility</option>
						<option value="MARKETING">Marketing</option>
						<option value="AUTHENTICATION">Authentication</option>
					</select>
				</label>
				<label>
					<span>Header</span>
					<select v-model="form.header_type">
						<option value="">No header</option>
						<option value="TEXT">Text</option>
						<option value="IMAGE">Image</option>
						<option value="VIDEO">Video</option>
						<option value="DOCUMENT">Document</option>
						<option value="LOCATION">Location</option>
					</select>
				</label>
			</div>
			<label v-if="form.header_type === 'TEXT'">
				<span>Header text</span>
				<input v-model="form.header_content" type="text" maxlength="1024" />
			</label>
			<label>
				<span>Body</span>
				<textarea
					v-model="form.body_text"
					rows="7"
					maxlength="4096"
					placeholder="Use {{1}}, {{2}} for variables."
					required
				/>
			</label>
			<label>
				<span>Footer</span>
				<input v-model="form.footer_text" type="text" maxlength="1024" />
			</label>
			<p v-if="submitError" class="form-error" role="alert">{{ submitError }}</p>
		</form>
		<template #footer>
			<div class="dialog-actions">
				<button
					type="button"
					class="secondary"
					:disabled="saving"
					@click="emit('update:modelValue', false)"
				>
					Cancel
				</button>
				<button type="button" class="primary" :disabled="saving" @click="submit">
					{{ saving ? 'Submitting…' : 'Submit to Meta' }}
				</button>
			</div>
		</template>
	</AppDialog>
</template>

<style scoped>
	.template-editor,
	.template-editor label {
		display: grid;
		gap: 7px;
	}

	.template-editor {
		gap: 16px;
	}

	.field-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
	}

	label span {
		color: var(--wa-muted);
		font-size: 12px;
		font-weight: 650;
	}

	input,
	select,
	textarea {
		width: 100%;
		min-height: 44px;
		box-sizing: border-box;
		padding: 10px 12px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		color: var(--wa-text);
		background: var(--wa-surface);
		font: inherit;
	}

	textarea {
		min-height: 132px;
		resize: vertical;
	}

	input:focus,
	select:focus,
	textarea:focus {
		outline: 2px solid color-mix(in srgb, var(--wa-success) 35%, transparent);
		outline-offset: 1px;
		border-color: var(--wa-success);
	}

	input:disabled {
		color: var(--wa-muted);
		background: var(--wa-surface-soft);
	}

	.form-error {
		margin: 0;
		padding: 10px 12px;
		border-radius: 9px;
		color: var(--wa-danger);
		background: var(--wa-danger-soft);
		font-size: 12px;
	}

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 9px;
	}

	.dialog-actions button {
		min-height: 44px;
		padding: 0 16px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		font: inherit;
		font-weight: 650;
		cursor: pointer;
	}

	.dialog-actions .secondary {
		color: var(--wa-text);
		background: var(--wa-surface);
	}

	.dialog-actions .primary {
		border-color: var(--wa-success);
		color: white;
		background: var(--wa-success);
	}

	.dialog-actions button:disabled {
		opacity: 0.6;
		cursor: wait;
	}

	@media (max-width: 620px) {
		.field-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
