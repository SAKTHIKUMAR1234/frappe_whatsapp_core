<script setup>
	import { computed, reactive, ref, watch } from 'vue'

	import AppDialog from '@/components/AppDialog.vue'
	import ChannelSelect from '@/features/channels/components/ChannelSelect.vue'
	import { call, errorMessage } from '@/services/frappe'
	import {
		TEMPLATE_BUTTON_TYPES,
		addTemplateButton,
		templateForm,
		templateRequest,
		templateSampleFields,
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
	const sampleFields = computed(() => templateSampleFields(form))
	const mediaHeader = computed(() => ['IMAGE', 'VIDEO', 'DOCUMENT'].includes(form.header_type))

	function reset() {
		try {
			Object.assign(form, templateForm(props.template || {}, props.accounts))
			submitError.value = ''
		} catch (error) {
			submitError.value = `This stored template cannot be edited safely: ${error.message}`
		}
	}

	function addButton() {
		addTemplateButton(form)
	}

	function removeButton(index) {
		form.buttons.splice(index, 1)
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
		:header="editing ? 'Edit WhatsApp template' : 'Create WhatsApp template'"
		width="820px"
		@update:model-value="emit('update:modelValue', $event)"
	>
		<form class="template-editor" @submit.prevent="save(true)">
			<div v-if="editing" class="status-panel">
				<div>
					<strong>{{ template.approval_status }}</strong>
				</div>
				<p v-if="template.status_reason">{{ template.status_reason }}</p>
				<p v-if="template.correct_category">
					Meta suggested category: {{ template.correct_category }}
				</p>
			</div>

			<section class="editor-section">
				<div class="section-heading">
					<strong>Template details</strong>
				</div>
				<div class="field-grid">
					<label>
						<span>WhatsApp account</span>
						<ChannelSelect
							v-model="form.account_name"
							:options="accounts"
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
							placeholder="en_US"
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
						<span>Parameter format</span>
						<select v-model="form.parameter_format">
							<option value="POSITIONAL">
								Positional — &#123;&#123;1&#125;&#125;
							</option>
							<option value="NAMED">
								Named — &#123;&#123;customer_name&#125;&#125;
							</option>
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
				</div>
			</section>

			<section class="editor-section">
				<div class="section-heading">
					<strong>Header</strong>
				</div>
				<div class="field-grid">
					<label>
						<span>Header type</span>
						<select v-model="form.header_type">
							<option value="NONE">No header</option>
							<option value="TEXT">Text</option>
							<option value="IMAGE">Image</option>
							<option value="VIDEO">Video</option>
							<option value="DOCUMENT">Document</option>
							<option value="LOCATION">Location</option>
						</select>
					</label>
					<label v-if="form.header_type === 'TEXT'">
						<span>Header text</span>
						<input
							v-model="form.header_text"
							type="text"
							maxlength="1024"
							placeholder="Order {{1}}"
						/>
					</label>
					<label v-if="mediaHeader" class="wide-field">
						<span>Media sample handle or public URL</span>
						<input
							v-model="form.header_media_example"
							type="text"
							placeholder="Upload handle returned by Meta, or a valid sample URL"
						/>
					</label>
				</div>
			</section>

			<section class="editor-section">
				<div class="section-heading">
					<strong>Message</strong>
				</div>
				<label>
					<span>Body text</span>
					<textarea
						v-model="form.body_text"
						rows="5"
						placeholder="Hello {{1}}, your order is ready."
					/>
				</label>
				<label v-if="form.category === 'AUTHENTICATION'" class="checkbox-field">
					<input v-model="form.add_security_recommendation" type="checkbox" />
					<span>Add Meta's security recommendation</span>
				</label>
				<div class="field-grid">
					<label>
						<span>Footer (optional)</span>
						<input v-model="form.footer_text" type="text" maxlength="1024" />
					</label>
					<label v-if="form.category === 'AUTHENTICATION'">
						<span>Code expiration (minutes)</span>
						<input
							v-model="form.code_expiration_minutes"
							type="number"
							min="1"
							step="1"
						/>
					</label>
				</div>
			</section>

			<section class="editor-section">
				<div class="section-heading">
					<strong>Sample values</strong>
				</div>
				<div v-if="sampleFields.length" class="field-grid">
					<label v-for="field in sampleFields" :key="field.key">
						<span>{{ field.label }}</span>
						<input
							v-model="form.sample_values[field.scope][field.name]"
							type="text"
							placeholder="Enter a realistic sample value"
						/>
					</label>
				</div>
				<p v-else class="empty-note">
					Add a body or text-header variable such as &#123;&#123;1&#125;&#125; to enter
					its sample value here. Media and dynamic-button samples remain beside the
					fields they describe.
				</p>
			</section>

			<section class="editor-section">
				<div class="section-heading">
					<strong>Buttons</strong>
					<button type="button" class="secondary compact" @click="addButton">
						Add button
					</button>
				</div>
				<p v-if="!form.buttons.length" class="empty-note">No buttons configured.</p>
				<article
					v-for="(button, index) in form.buttons"
					:key="button._client_key"
					class="button-card"
				>
					<div class="button-card-heading">
						<strong>Button {{ index + 1 }}</strong>
						<button type="button" class="danger-link" @click="removeButton(index)">
							Remove
						</button>
					</div>
					<div class="field-grid">
						<label>
							<span>Action</span>
							<select v-model="button.type">
								<option
									v-for="option in TEMPLATE_BUTTON_TYPES"
									:key="option.value"
									:value="option.value"
								>
									{{ option.label }}
								</option>
							</select>
						</label>
						<label v-if="button.type !== 'CATALOG'">
							<span>Button text</span>
							<input v-model="button.text" type="text" maxlength="80" />
						</label>
						<label v-if="button.type === 'URL'" class="wide-field">
							<span>Website URL</span>
							<input
								v-model="button.url"
								type="url"
								placeholder="https://example.com/{{1}}"
							/>
						</label>
						<label v-if="['URL', 'COPY_CODE'].includes(button.type)">
							<span>Example value</span>
							<input v-model="button.example_value" type="text" />
						</label>
						<label v-if="button.type === 'PHONE_NUMBER'">
							<span>Phone number</span>
							<input
								v-model="button.phone_number"
								type="tel"
								placeholder="+919876543210"
							/>
						</label>
						<label v-if="button.type === 'OTP'">
							<span>OTP action</span>
							<select v-model="button.otp_type">
								<option value="COPY_CODE">Copy code</option>
								<option value="ONE_TAP">One tap</option>
								<option value="ZERO_TAP">Zero tap</option>
							</select>
						</label>
						<label v-if="button.type === 'OTP' && button.otp_type !== 'COPY_CODE'">
							<span>Autofill text</span>
							<input v-model="button.autofill_text" type="text" />
						</label>
						<label v-if="button.type === 'OTP' && button.otp_type === 'ZERO_TAP'">
							<span>Android package name</span>
							<input v-model="button.package_name" type="text" />
						</label>
						<label v-if="button.type === 'OTP' && button.otp_type === 'ZERO_TAP'">
							<span>App signature hash</span>
							<input v-model="button.signature_hash" type="text" />
						</label>
						<label v-if="button.type === 'FLOW'">
							<span>Flow ID</span>
							<input v-model="button.flow_id" type="text" />
						</label>
						<label v-if="button.type === 'FLOW'">
							<span>Flow action</span>
							<select v-model="button.flow_action">
								<option value="navigate">Navigate</option>
								<option value="data_exchange">Data exchange</option>
							</select>
						</label>
						<label v-if="button.type === 'FLOW' && button.flow_action === 'navigate'">
							<span>Initial screen</span>
							<input v-model="button.navigate_screen" type="text" />
						</label>
						<label v-if="button.type === 'CATALOG'">
							<span>Thumbnail product retailer ID (optional)</span>
							<input v-model="button.thumbnail_product_retailer_id" type="text" />
						</label>
						<label v-if="button.type === 'VOICE_CALL'">
							<span>Call availability (minutes)</span>
							<input
								v-model="button.ttl_minutes"
								type="number"
								min="1440"
								max="43200"
							/>
						</label>
					</div>
				</article>
			</section>

			<div v-if="form.advanced_component_count" class="preserved-note">
				<strong>Advanced Meta content preserved</strong>
				<span>
					{{ form.advanced_component_count }} advanced component(s), such as carousel or
					limited-time content, will be retained unchanged while these fields are edited.
				</span>
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

	.editor-section,
	.button-card,
	.sample-panel {
		display: grid;
		gap: 14px;
		padding: 16px;
		border: 1px solid var(--wa-border);
		border-radius: 12px;
		background: var(--wa-surface);
	}

	.sample-panel,
	.button-card {
		padding: 14px;
		background: var(--wa-surface-soft);
	}

	.section-heading,
	.button-card-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.section-heading strong,
	.section-heading small {
		display: block;
	}

	.section-heading small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}

	.compact-heading {
		align-items: flex-start;
	}

	.field-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
	}

	.wide-field {
		grid-column: 1 / -1;
	}

	label span,
	.status-panel span,
	.preserved-note span {
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
		min-height: 120px;
		resize: vertical;
		line-height: 1.5;
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

	.checkbox-field {
		display: flex !important;
		grid-template-columns: auto 1fr;
		align-items: center;
		justify-content: flex-start;
		gap: 9px !important;
	}

	.checkbox-field input {
		width: 18px;
		min-height: 18px;
	}

	.status-panel,
	.preserved-note {
		display: grid;
		gap: 7px;
		padding: 12px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		background: var(--wa-surface-soft);
	}

	.status-panel strong,
	.status-panel span,
	.preserved-note strong,
	.preserved-note span {
		display: block;
	}

	.status-panel p,
	.empty-note {
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

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 9px;
	}

	.dialog-actions button,
	.editor-section button,
	.button-card button {
		min-height: 44px;
		padding: 0 16px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		font: inherit;
		font-weight: 650;
		cursor: pointer;
	}

	.compact {
		min-height: 36px !important;
	}

	.secondary {
		color: var(--wa-text);
		background: var(--wa-surface);
	}

	.primary {
		border-color: var(--wa-success) !important;
		color: white;
		background: var(--wa-success);
	}

	.danger-link {
		min-height: auto !important;
		padding: 3px 0 !important;
		border: 0 !important;
		color: var(--wa-danger);
		background: transparent;
	}

	button:disabled {
		opacity: 0.6;
		cursor: wait;
	}

	@media (max-width: 620px) {
		.field-grid {
			grid-template-columns: 1fr;
		}

		.wide-field {
			grid-column: auto;
		}
	}
</style>
