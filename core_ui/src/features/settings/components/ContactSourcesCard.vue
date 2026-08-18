<script setup>
	import { computed, onMounted, reactive, ref } from 'vue'
	import Button from 'primevue/button'
	import AppDialog from '@/components/AppDialog.vue'
	import InputNumber from 'primevue/inputnumber'
	import InputText from 'primevue/inputtext'
	import Message from 'primevue/message'
	import Textarea from 'primevue/textarea'
	import ToggleSwitch from 'primevue/toggleswitch'
	import { useToast } from 'primevue/usetoast'
	import { ContactRound, Pencil, Plus } from 'lucide-vue-next'

	import AsyncState from '@/components/AsyncState.vue'
	import LinkField from '@/components/form/LinkField.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { focusDialogControl } from '@/utils/focus'

	const props = defineProps({
		sources: { type: Array, default: () => [] },
		canManage: { type: Boolean, default: false },
	})
	const emit = defineEmits(['saved'])
	const toast = useToast()
	const loadingOptions = ref(false)
	const optionError = ref('')
	const saving = ref(false)
	const visible = ref(false)
	const dialogRef = ref(null)
	const doctypes = ref([])
	const fieldOptions = ref({ fields: [], phone_fields: [] })
	const form = reactive({
		name: '',
		source_key: '',
		display_name: '',
		source_doctype: '',
		enabled: true,
		auto_resolve: true,
		priority: 100,
		phone_field: '',
		display_name_field: '',
		entity_type_field: '',
		filters: '',
	})
	const title = computed(() => (form.name ? 'Edit contact source' : 'Add contact source'))

	async function loadDoctypes() {
		if (!props.canManage) return
		loadingOptions.value = true
		optionError.value = ''
		try {
			doctypes.value = await call(
				'frappe_whatsapp_core.frontend_api.contact_source_doctypes',
			)
		} catch (error) {
			optionError.value = errorMessage(error, 'Unable to load Frappe DocTypes.')
		} finally {
			loadingOptions.value = false
		}
	}

	async function loadFields() {
		fieldOptions.value = { fields: [], phone_fields: [] }
		if (!form.source_doctype) return
		loadingOptions.value = true
		optionError.value = ''
		try {
			fieldOptions.value = await call(
				'frappe_whatsapp_core.frontend_api.contact_source_fields',
				{ source_doctype: form.source_doctype },
			)
		} catch (error) {
			optionError.value = errorMessage(error, 'Unable to inspect this DocType.')
		} finally {
			loadingOptions.value = false
		}
	}

	async function open(source = null) {
		Object.assign(form, {
			name: source?.name || '',
			source_key: source?.source_key || '',
			display_name: source?.display_name || '',
			source_doctype: source?.source_doctype || '',
			enabled: source ? Boolean(source.enabled) : true,
			auto_resolve: source ? Boolean(source.auto_resolve) : true,
			priority: source?.priority || 100,
			phone_field: source?.phone_field || '',
			display_name_field: source?.display_name_field || '',
			entity_type_field: source?.entity_type_field || '',
			filters: source?.filters || '',
		})
		visible.value = true
		await loadFields()
	}

	async function changeDoctype() {
		form.phone_field = ''
		form.display_name_field = ''
		form.entity_type_field = ''
		if (!form.display_name) form.display_name = form.source_doctype
		await loadFields()
	}

	async function save() {
		if (!form.display_name.trim() || !form.source_doctype || !form.phone_field) return
		saving.value = true
		try {
			await call('frappe_whatsapp_core.frontend_api.save_contact_source', {
				source: { ...form },
			})
			visible.value = false
			emit('saved')
			toast.add({
				severity: 'success',
				summary: 'Contact source saved',
				detail: `${form.display_name} can now resolve WhatsApp contacts.`,
				life: 3000,
			})
		} catch (error) {
			optionError.value = errorMessage(error, 'Unable to save this contact source.')
		} finally {
			saving.value = false
		}
	}

	onMounted(loadDoctypes)
</script>

<template>
	<section class="surface-card source-card">
		<header>
			<div class="source-title">
				<span><ContactRound :size="18" /></span>
				<div>
					<div class="eyebrow">Business contact mapping</div>
					<h2>Contact sources</h2>
					<p>Link WhatsApp identities to existing business records.</p>
				</div>
			</div>
			<Button v-if="canManage" label="Add source" size="small" @click="open()">
				<template #icon><Plus :size="15" /></template>
			</Button>
		</header>
		<AsyncState v-if="optionError && !visible" :error="optionError" @retry="loadDoctypes" />
		<div v-else-if="sources.length" class="source-list">
			<article v-for="source in sources" :key="source.name">
				<div class="source-main">
					<strong>{{ source.display_name }}</strong>
					<span>{{ source.source_doctype }} · {{ source.phone_field }}</span>
				</div>
				<div class="source-state">
					<span :class="{ active: source.enabled }">{{
						source.enabled ? 'Active' : 'Paused'
					}}</span>
					<small>Priority {{ source.priority }}</small>
				</div>
				<Button
					v-if="canManage"
					text
					rounded
					severity="secondary"
					:aria-label="`Edit ${source.display_name}`"
					@click="open(source)"
				>
					<Pencil :size="15" />
				</Button>
			</article>
		</div>
		<div v-else class="empty-source">
			<ContactRound :size="24" />
			<strong>No business contact source configured</strong>
			<span
				>Messages still work by phone number. Add a DocType mapping to show business
				context.</span
			>
		</div>

		<AppDialog
			ref="dialogRef"
			v-model:visible="visible"
			modal
			:header="title"
			class="contact-source-dialog"
			@show="focusDialogControl(dialogRef, '[role=combobox]')"
		>
			<div class="source-form">
				<Message v-if="optionError" severity="error" :closable="false">{{
					optionError
				}}</Message>
				<label>
					<span>Source DocType *</span>
					<LinkField
						v-model="form.source_doctype"
						aria-label="Source DocType"
						:options="doctypes"
						option-label="name"
						option-value="name"
						:disabled="Boolean(form.name) || loadingOptions"
						placeholder="Choose a Frappe DocType"
						@change="changeDoctype"
					/>
				</label>
				<label>
					<span>Contact label *</span>
					<InputText v-model="form.display_name" fluid placeholder="Customers" />
				</label>
				<label>
					<span>Phone field *</span>
					<LinkField
						v-model="form.phone_field"
						:options="fieldOptions.phone_fields"
						option-label="label"
						option-value="value"
						:disabled="loadingOptions"
						placeholder="Field that contains the WhatsApp number"
					/>
				</label>
				<label>
					<span>Display name field</span>
					<LinkField
						v-model="form.display_name_field"
						:options="fieldOptions.fields"
						option-label="label"
						option-value="value"
						:show-clear="true"
						placeholder="Use document name"
					/>
				</label>
				<label>
					<span>Contact type field</span>
					<LinkField
						v-model="form.entity_type_field"
						:options="fieldOptions.fields"
						option-label="label"
						option-value="value"
						:show-clear="true"
						placeholder="Optional"
					/>
				</label>
				<label>
					<span>Resolution priority</span>
					<InputNumber v-model="form.priority" :min="1" :max="9999" fluid />
				</label>
				<label class="switch-row">
					<ToggleSwitch v-model="form.enabled" />
					<span
						><strong>Enabled</strong
						><small>Use this mapping for contacts.</small></span
					>
				</label>
				<label class="switch-row">
					<ToggleSwitch v-model="form.auto_resolve" />
					<span
						><strong>Resolve inbound contacts</strong
						><small>Match new messages automatically.</small></span
					>
				</label>
				<details class="advanced">
					<summary>Advanced filters</summary>
					<label>
						<span>Frappe filters (JSON object)</span>
						<Textarea
							v-model="form.filters"
							rows="4"
							fluid
							placeholder='{"disabled": 0}'
						/>
					</label>
				</details>
			</div>
			<template #footer>
				<Button label="Cancel" text @click="visible = false" />
				<Button
					label="Save contact source"
					:loading="saving"
					:disabled="
						!form.display_name.trim() || !form.source_doctype || !form.phone_field
					"
					@click="save"
				/>
			</template>
		</AppDialog>
	</section>
</template>

<style scoped>
	.source-card {
		margin-bottom: 16px;
		overflow: hidden;
	}
	header {
		padding: 17px 18px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
		border-bottom: 1px solid var(--wa-border);
	}
	.source-title {
		display: flex;
		align-items: center;
		gap: 11px;
		min-width: 0;
	}
	.source-title > span {
		width: 37px;
		height: 37px;
		display: grid;
		place-items: center;
		flex: none;
		border-radius: 11px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}
	header h2 {
		margin: 3px 0 0;
		font-size: 15px;
	}
	header p {
		margin: 4px 0 0;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.source-list {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
		padding: 14px 18px 18px;
	}
	.source-list article {
		min-width: 0;
		padding: 13px;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto;
		align-items: center;
		gap: 12px;
		border: 1px solid var(--wa-border);
		border-radius: 12px;
		background: var(--wa-surface-muted);
	}
	.source-main strong,
	.source-main span,
	.source-state span,
	.source-state small {
		display: block;
	}
	.source-main strong {
		overflow: hidden;
		color: var(--wa-text);
		font-size: 12px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.source-main span,
	.source-state small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.source-state {
		text-align: right;
	}
	.source-state span {
		color: var(--wa-muted);
		font-size: 12px;
		font-weight: 700;
	}
	.source-state span.active {
		color: var(--wa-success);
	}
	.empty-source {
		padding: 28px 18px;
		display: grid;
		justify-items: center;
		gap: 6px;
		color: var(--wa-muted);
		text-align: center;
	}
	.empty-source strong {
		color: var(--wa-text);
		font-size: 13px;
	}
	.empty-source span {
		max-width: 520px;
		font-size: 11px;
		line-height: 1.5;
	}
	.source-form {
		width: min(680px, 82vw);
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
	}
	.source-form > label:not(.switch-row),
	.advanced label {
		display: grid;
		gap: 6px;
		color: var(--wa-muted);
		font-size: 11px;
		font-weight: 700;
	}
	.source-form > .p-message,
	.advanced {
		grid-column: 1 / -1;
	}
	.switch-row {
		padding: 11px 12px;
		display: flex;
		align-items: center;
		gap: 10px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
	}
	.switch-row strong,
	.switch-row small {
		display: block;
	}
	.switch-row strong {
		font-size: 11px;
	}
	.switch-row small {
		margin-top: 2px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.advanced {
		padding: 11px 12px;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
	}
	.advanced summary {
		cursor: pointer;
		color: var(--wa-text);
		font-size: 11px;
		font-weight: 700;
	}
	.advanced label {
		margin-top: 12px;
	}
	@media (max-width: 760px) {
		header {
			align-items: flex-start;
		}
		header p {
			display: none;
		}
		.source-list {
			grid-template-columns: 1fr;
			padding: 12px;
		}
		.source-form {
			width: 100%;
			grid-template-columns: 1fr;
		}
		.source-form > .p-message,
		.advanced {
			grid-column: auto;
		}
		.source-list article {
			grid-template-columns: minmax(0, 1fr) auto auto;
		}
	}
</style>
