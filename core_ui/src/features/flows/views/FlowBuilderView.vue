<script setup>
	import { computed, onMounted, reactive, ref } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import InputText from 'primevue/inputtext'
	import MultiSelect from 'primevue/multiselect'
	import Tag from 'primevue/tag'
	import Textarea from 'primevue/textarea'
	import { useConfirm } from 'primevue/useconfirm'
	import { useToast } from 'primevue/usetoast'
	import {
		ArrowLeft,
		CloudUpload,
		Copy,
		ExternalLink,
		RefreshCw,
		Save,
		Send,
		ShieldCheck,
	} from 'lucide-vue-next'
	import {
		createFlow,
		deprecateFlow,
		getFlow,
		publishFlow,
		updateFlow,
		uploadFlowJson,
	} from '@/features/flows/services/flowService'
	import { errorMessage } from '@/services/frappe'
	import { useSessionStore } from '@/stores/session'

	const route = useRoute()
	const router = useRouter()
	const toast = useToast()
	const confirm = useConfirm()
	const session = useSessionStore()
	const loading = ref(true)
	const saving = ref(false)
	const uploading = ref(false)
	const lifecycle = ref(false)
	const data = ref(null)
	const form = reactive({ name: '', categories: [], endpoint_uri: '', flow_json: '' })
	const categories = [
		'SIGN_UP',
		'SIGN_IN',
		'APPOINTMENT_BOOKING',
		'LEAD_GENERATION',
		'CONTACT_US',
		'CUSTOMER_SUPPORT',
		'SURVEY',
		'OTHER',
	]
	const accountName = computed(() => String(route.query.account || ''))
	const flowId = computed(() => String(route.params.flowName || ''))
	const flow = computed(() => data.value?.flow || {})
	const canManage = computed(() => Boolean(session.boot?.can_manage))
	const mutable = computed(() => flow.value.status === 'DRAFT')
	const previewUrl = computed(() => flow.value.preview?.preview_url || '')
	const validationErrors = computed(() => flow.value.validation_errors || [])

	async function load() {
		if (!accountName.value) {
			router.replace({ name: 'flows' })
			return
		}
		loading.value = true
		try {
			data.value = await getFlow(accountName.value, flowId.value)
			form.name = flow.value.name || ''
			form.categories = [...(flow.value.categories || [])]
			form.endpoint_uri = flow.value.endpoint_uri || flow.value.data_channel_uri || ''
			form.flow_json = data.value.flow_json
				? JSON.stringify(data.value.flow_json, null, 2)
				: ''
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Flow not loaded',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			loading.value = false
		}
	}

	async function saveMetadata() {
		saving.value = true
		try {
			await updateFlow({
				account_name: accountName.value,
				flow_id: flowId.value,
				flow_name: form.name,
				categories: form.categories,
				endpoint_uri: form.endpoint_uri,
			})
			toast.add({ severity: 'success', summary: 'Meta Flow details saved', life: 2500 })
			await load()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Details not saved',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			saving.value = false
		}
	}

	async function uploadJson() {
		let parsed
		try {
			parsed = JSON.parse(form.flow_json)
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Invalid JSON',
				detail: error.message,
				life: 5000,
			})
			return
		}
		uploading.value = true
		try {
			const result = await uploadFlowJson(accountName.value, flowId.value, parsed)
			const errors = result.data?.validation_errors || []
			toast.add({
				severity: errors.length ? 'warn' : 'success',
				summary: errors.length
					? `${errors.length} Meta validation errors`
					: 'flow.json validated by Meta',
				life: 4000,
			})
			await load()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'flow.json not uploaded',
				detail: errorMessage(error),
				life: 6000,
			})
		} finally {
			uploading.value = false
		}
	}

	function requestPublish() {
		confirm.require({
			header: 'Publish this Meta Flow?',
			message: 'Publishing is irreversible. To change it later, clone it into a new draft.',
			icon: 'pi pi-exclamation-triangle',
			rejectLabel: 'Keep draft',
			acceptLabel: 'Publish',
			accept: doPublish,
		})
	}

	async function doPublish() {
		lifecycle.value = true
		try {
			await publishFlow(accountName.value, flowId.value)
			toast.add({ severity: 'success', summary: 'Flow published on Meta', life: 3000 })
			await load()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Publish failed',
				detail: errorMessage(error),
				life: 6000,
			})
		} finally {
			lifecycle.value = false
		}
	}

	async function cloneDraft() {
		lifecycle.value = true
		try {
			const result = await createFlow({
				account_name: accountName.value,
				flow_name: `${flow.value.name} Copy`,
				categories: flow.value.categories || ['OTHER'],
				endpoint_uri: form.endpoint_uri || null,
				clone_flow_id: flowId.value,
			})
			const id = result.data?.id
			if (!id) throw new Error('Meta did not return a cloned Flow ID')
			router.replace({
				name: 'flow-builder',
				params: { flowName: id },
				query: { account: accountName.value },
			})
			await load()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Clone failed',
				detail: errorMessage(error),
				life: 6000,
			})
		} finally {
			lifecycle.value = false
		}
	}

	function requestDeprecate() {
		confirm.require({
			header: 'Deprecate this Flow?',
			message: 'Customers will no longer be able to open this Flow.',
			rejectLabel: 'Cancel',
			acceptLabel: 'Deprecate',
			acceptClass: 'p-button-danger',
			accept: async () => {
				lifecycle.value = true
				try {
					await deprecateFlow(accountName.value, flowId.value)
					await load()
				} catch (error) {
					toast.add({
						severity: 'error',
						summary: 'Deprecation failed',
						detail: errorMessage(error),
						life: 6000,
					})
				} finally {
					lifecycle.value = false
				}
			},
		})
	}

	onMounted(load)
</script>

<template>
	<div class="native-flow-page">
		<header class="builder-header">
			<div class="title-row">
				<Button text rounded aria-label="Back" @click="router.push({ name: 'flows' })"
					><ArrowLeft :size="19"
				/></Button>
				<div>
					<div class="eyebrow">Native Meta Flow · {{ accountName }}</div>
					<h1>{{ flow.name || 'WhatsApp Flow' }}</h1>
					<small>Meta Flow ID {{ flowId }}</small>
				</div>
			</div>
			<div class="header-actions">
				<Tag
					v-if="flow.status"
					:value="flow.status"
					:severity="
						flow.status === 'PUBLISHED'
							? 'success'
							: flow.status === 'DEPRECATED'
								? 'danger'
								: 'warn'
					"
					rounded
				/>
				<Button outlined aria-label="Reload" :loading="loading" @click="load"
					><RefreshCw :size="16"
				/></Button>
				<Button
					v-if="previewUrl"
					label="Meta preview"
					outlined
					as="a"
					:href="previewUrl"
					target="_blank"
					><template #icon><ExternalLink :size="15" /></template
				></Button>
				<Button
					v-if="canManage && !mutable && flow.status !== 'DEPRECATED'"
					label="Clone draft"
					:loading="lifecycle"
					@click="cloneDraft"
					><template #icon><Copy :size="15" /></template
				></Button>
				<Button
					v-if="canManage && mutable"
					label="Publish"
					:loading="lifecycle"
					:disabled="validationErrors.length > 0 || !data?.flow_json"
					@click="requestPublish"
					><template #icon><Send :size="15" /></template
				></Button>
				<Button
					v-if="canManage && flow.status === 'PUBLISHED'"
					label="Deprecate"
					severity="danger"
					outlined
					@click="requestDeprecate"
				/>
			</div>
		</header>

		<div v-if="loading" class="loading-card surface-card">
			Loading the Meta Flow and its current asset…
		</div>
		<div v-else class="builder-grid">
			<section class="surface-card metadata-card">
				<div class="section-title">
					<ShieldCheck :size="18" />
					<div>
						<strong>Meta configuration</strong><span>Stored and enforced by Meta</span>
					</div>
				</div>
				<label>Name</label
				><InputText v-model="form.name" fluid :disabled="!mutable || !canManage" />
				<label>Categories</label
				><MultiSelect
					v-model="form.categories"
					:options="categories"
					display="chip"
					fluid
					:disabled="!mutable || !canManage"
				/>
				<label>Data endpoint URL</label
				><InputText
					v-model="form.endpoint_uri"
					fluid
					:disabled="!mutable || !canManage"
					placeholder="Optional for static Flows"
				/>
				<Button
					v-if="canManage && mutable"
					label="Save configuration"
					:loading="saving"
					outlined
					fluid
					@click="saveMetadata"
					><template #icon><Save :size="15" /></template
				></Button>
				<div class="facts">
					<div>
						<span>JSON version</span><strong>{{ flow.json_version || '—' }}</strong>
					</div>
					<div>
						<span>Data API</span><strong>{{ flow.data_api_version || '—' }}</strong>
					</div>
					<div>
						<span>Message health</span
						><strong>{{ flow.health_status?.can_send_message || '—' }}</strong>
					</div>
				</div>
			</section>

			<section class="surface-card json-card">
				<header>
					<div>
						<strong>flow.json</strong
						><span>The asset is uploaded directly to Meta for schema validation.</span>
					</div>
					<Button
						v-if="canManage && mutable"
						label="Upload and validate"
						:loading="uploading"
						:disabled="!form.flow_json.trim()"
						@click="uploadJson"
						><template #icon><CloudUpload :size="15" /></template
					></Button>
				</header>
				<Textarea
					v-model="form.flow_json"
					class="json-editor"
					:readonly="!mutable || !canManage"
					spellcheck="false"
					placeholder="Paste a Meta WhatsApp flow.json document"
				/>
				<div v-if="validationErrors.length" class="validation-panel">
					<strong>Meta validation errors</strong>
					<article v-for="(error, index) in validationErrors" :key="index">
						<b>{{ error.error || error.error_type || 'Validation error' }}</b
						><span>{{ error.message }}</span
						><small v-if="error.line_start"
							>Line {{ error.line_start }}, column {{ error.column_start }}</small
						>
					</article>
				</div>
				<div v-else-if="data?.flow_json" class="valid-panel">
					<ShieldCheck :size="16" />Current Meta asset has no reported validation errors.
				</div>
			</section>
		</div>
	</div>
</template>

<style scoped>
	.native-flow-page {
		margin: -30px;
		min-height: calc(100vh - 68px);
		background: #f4f7f5;
	}
	.builder-header {
		min-height: 78px;
		padding: 13px 24px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		border-bottom: 1px solid var(--wa-border);
		background: white;
	}
	.title-row,
	.header-actions,
	.section-title,
	.json-card > header {
		display: flex;
		align-items: center;
		gap: 11px;
	}
	.title-row h1 {
		margin: 2px 0;
		font-size: 18px;
	}
	.title-row small {
		color: #85928b;
		font-size: 9px;
	}
	.header-actions {
		flex-wrap: wrap;
		justify-content: flex-end;
	}
	.builder-grid {
		padding: 22px;
		display: grid;
		grid-template-columns: 330px minmax(0, 1fr);
		gap: 18px;
	}
	.metadata-card,
	.json-card {
		padding: 18px;
	}
	.section-title div,
	.json-card header > div {
		display: flex;
		flex-direction: column;
	}
	.section-title span,
	.json-card header span {
		margin-top: 2px;
		color: #7f8c85;
		font-size: 9px;
	}
	label {
		display: block;
		margin: 17px 0 7px;
		font-size: 10px;
		font-weight: 700;
	}
	.metadata-card > .p-button {
		margin-top: 18px;
	}
	.facts {
		margin-top: 20px;
		padding-top: 13px;
		display: grid;
		gap: 9px;
		border-top: 1px solid var(--wa-border);
	}
	.facts div {
		display: flex;
		justify-content: space-between;
		font-size: 9px;
	}
	.facts span {
		color: #77857e;
	}
	.json-card > header {
		justify-content: space-between;
		margin-bottom: 13px;
	}
	.json-editor {
		width: 100%;
		min-height: calc(100vh - 235px);
		resize: vertical;
		font-family: 'SFMono-Regular', Consolas, monospace;
		font-size: 11px;
		line-height: 1.55;
		white-space: pre;
	}
	.validation-panel {
		margin-top: 12px;
		padding: 12px;
		border: 1px solid #f2c7c4;
		border-radius: 10px;
		background: #fff3f2;
	}
	.validation-panel > strong {
		color: #9d2924;
		font-size: 11px;
	}
	.validation-panel article {
		margin-top: 9px;
		display: flex;
		flex-direction: column;
		gap: 3px;
		font-size: 10px;
	}
	.validation-panel small {
		color: #9a625f;
	}
	.valid-panel {
		margin-top: 12px;
		padding: 10px;
		display: flex;
		align-items: center;
		gap: 8px;
		border-radius: 9px;
		color: #087354;
		background: #e4f8ef;
		font-size: 10px;
	}
	.loading-card {
		margin: 25px;
		padding: 40px;
		color: #78857e;
		text-align: center;
	}
	@media (max-width: 1000px) {
		.builder-header {
			align-items: flex-start;
			flex-direction: column;
		}
		.header-actions {
			justify-content: flex-start;
		}
		.builder-grid {
			grid-template-columns: 1fr;
		}
		.json-editor {
			min-height: 55vh;
		}
	}
	@media (max-width: 600px) {
		.native-flow-page {
			margin: -18px;
		}
		.builder-header,
		.builder-grid {
			padding: 14px;
		}
	}
</style>
