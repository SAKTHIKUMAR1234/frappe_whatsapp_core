<script setup>
	import { computed, reactive, ref, watch } from 'vue'

	import AppDialog from '@/components/AppDialog.vue'
	import Select from 'primevue/select'
	import { call, errorMessage } from '@/services/frappe'
	import {
		formatTemplateComponents,
		templateForm,
		templateRequest,
	} from '@/features/templates/templateAuthoring'

	const props = defineProps({
		modelValue: { type: Boolean, default: false },
		template: { type: Object, default: null },
		accounts: { type: Array, default: () => [] },
	})
	const emit = defineEmits(['update:modelValue', 'saved'])
	const savingAction = ref('')
	const submitError = ref('')
	const editing = computed(() => Boolean(props.template?.name))
	const canSaveDraft = computed(
		() => !editing.value || props.template?.approval_status === 'DRAFT',
	)
	const form = reactive(templateForm())

	function reset() {
		try {
			Object.assign(form, templateForm(props.template || {}, props.accounts))
			submitError.value = ''
		} catch (error) {
			submitError.value = `This stored template cannot be edited safely: ${error.message}`
		}
	}

	function formatComponents() {
		try {
			form.components_json = formatTemplateComponents(form.components_json)
			submitError.value = ''
		} catch (error) {
			submitError.value = error.message
		}
	}

	async function save(submit) {
		let request
		try {
			request = templateRequest(form, {
				templateKey: props.template?.name || null,
				submit,
			})
		} catch (error) {
			submitError.value = error.message
			return
		}
		savingAction.value = submit ? 'submit' : 'draft'
		submitError.value = ''
		try {
			const result = await call(
				'frappe_whatsapp_core.template_catalog.request_template_upsert',
				request,
			)
			emit('saved', result)
			if (!result?.success) {
				submitError.value =
					result?.error ||
					'Meta did not accept this template. The Integration draft was preserved.'
				return
			}
			emit('update:modelValue', false)
		} catch (error) {
			submitError.value = errorMessage(
				error,
				submit
					? 'Meta did not accept this template.'
					: 'Unable to save the template draft.',
			)
		} finally {
			savingAction.value = ''
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
		:header="editing ? 'Edit complete template' : 'Create complete template'"
		@update:model-value="emit('update:modelValue', $event)"
	>
		<form class="template-editor" @submit.prevent="save(true)">
			<div v-if="editing" class="status-panel">
				<div>
					<strong>{{ template.approval_status }}</strong>
					<span>Current Integration / Meta status</span>
				</div>
				<p v-if="template.status_reason">{{ template.status_reason }}</p>
				<p v-if="template.correct_category">
					Meta suggested category: {{ template.correct_category }}
				</p>
			</div>
			<div class="field-grid">
				<label>
					<span>WhatsApp account</span>
					<Select
						v-model="form.account_name"
						:options="accounts"
						option-label="display_name"
						option-value="account_name"
						:disabled="editing"
						placeholder="Select an account"
					/>
				</label>
				<label>
					<span>Template name</span>
					<input
						v-model="form.template_name"
						type="text"
						maxlength="512"
						pattern="[a-z0-9_]+"
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
					<span>Message send TTL (optional seconds)</span>
					<input
						v-model="form.message_send_ttl_seconds"
						type="number"
						min="1"
						step="1"
						placeholder="Meta default"
					/>
				</label>
				<label>
					<span>Parameter format</span>
					<select v-model="form.parameter_format">
						<option value="POSITIONAL">Positional variables</option>
						<option value="NAMED">Named variables</option>
					</select>
				</label>
			</div>
			<label class="components-field">
				<span>Complete Meta components document</span>
				<textarea
					v-model="form.components_json"
					rows="18"
					spellcheck="false"
					placeholder='[{"type":"BODY","text":"Your order {{1}} is ready"}]'
					required
				/>
				<small>
					This canonical array is preserved end-to-end. It supports text/media headers,
					examples, quick replies, URL/phone/OTP/Flow/catalog buttons, authentication,
					carousel cards and forward-compatible Meta component fields.
				</small>
			</label>
			<div class="component-actions">
				<button type="button" class="secondary compact" @click="formatComponents">
					Validate and format JSON
				</button>
			</div>
			<p v-if="submitError" class="form-error" role="alert">{{ submitError }}</p>
		</form>
		<template #footer>
			<div class="dialog-actions">
				<button
					type="button"
					class="secondary"
					:disabled="Boolean(savingAction)"
					@click="emit('update:modelValue', false)"
				>
					Cancel
				</button>
				<button
					v-if="canSaveDraft"
					type="button"
					class="secondary"
					:disabled="Boolean(savingAction)"
					@click="save(false)"
				>
					{{ savingAction === 'draft' ? 'Saving…' : 'Save draft' }}
				</button>
				<button
					type="button"
					class="primary"
					:disabled="Boolean(savingAction)"
					@click="save(true)"
				>
					{{ savingAction === 'submit' ? 'Submitting…' : 'Submit to Meta' }}
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

	label span,
	.status-panel span {
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
		min-height: 270px;
		resize: vertical;
		font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
		font-size: 12px;
		line-height: 1.55;
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

	.status-panel {
		display: grid;
		gap: 7px;
		padding: 12px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		background: var(--wa-surface-soft);
	}

	.status-panel strong,
	.status-panel span {
		display: block;
	}

	.status-panel p,
	.components-field small {
		margin: 0;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.form-error {
		margin: 0;
		padding: 10px 12px;
		border-radius: 9px;
		color: var(--wa-danger);
		background: var(--wa-danger-soft);
		font-size: 12px;
	}

	.component-actions,
	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 9px;
	}

	.dialog-actions button,
	.component-actions button {
		min-height: 44px;
		padding: 0 16px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		font: inherit;
		font-weight: 650;
		cursor: pointer;
	}

	.component-actions .compact {
		min-height: 36px;
	}

	.secondary {
		color: var(--wa-text);
		background: var(--wa-surface);
	}

	.primary {
		border-color: var(--wa-success);
		color: white;
		background: var(--wa-success);
	}

	button:disabled {
		opacity: 0.6;
		cursor: wait;
	}

	@media (max-width: 620px) {
		.field-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
