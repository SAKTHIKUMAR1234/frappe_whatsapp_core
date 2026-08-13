<script setup>
	import { computed, reactive, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import InputNumber from 'primevue/inputnumber'
	import InputText from 'primevue/inputtext'
	import Password from 'primevue/password'
	import Select from 'primevue/select'
	import ToggleSwitch from 'primevue/toggleswitch'
	import { useToast } from 'primevue/usetoast'
	import { KeyRound, Plus, RefreshCw, Save, Trash2 } from 'lucide-vue-next'

	import { call, errorMessage } from '@/services/frappe'

	const props = defineProps({
		workspace: { type: Object, required: true },
		canManage: { type: Boolean, default: false },
	})
	const emit = defineEmits(['saved'])
	const toast = useToast()
	const hubAccounts = ref([])
	const loadingAccounts = ref(false)
	let discoveryKey = ''
	const form = reactive({
		enabled: false,
		outbound_enabled: false,
		hub_url: '',
		relay_url: '',
		request_timeout: 30,
		default_country_calling_code: '91',
		api_key: '',
		api_secret: '',
		accounts: [],
		saving: false,
	})
	const hubAccountOptions = computed(() => {
		const options = hubAccounts.value.map((row) => ({
			...row,
			label: [row.verified_name || row.account_name || row.name, row.display_phone_number]
				.filter(Boolean)
				.join(' · '),
		}))
		const known = new Set(options.map((row) => row.name))
		for (const mapping of form.accounts) {
			if (mapping.account_name && !known.has(mapping.account_name)) {
				options.push({
					name: mapping.account_name,
					label: `${mapping.account_name} · saved mapping`,
				})
			}
		}
		return options
	})

	watch(
		() => props.workspace,
		(workspace) => {
			form.enabled = Boolean(workspace.transport?.enabled)
			form.outbound_enabled = Boolean(workspace.transport?.outbound_enabled)
			form.hub_url = workspace.transport?.hub_url || ''
			form.relay_url = workspace.transport?.relay_url || ''
			form.request_timeout = workspace.request_timeout || 30
			form.default_country_calling_code = workspace.default_country_calling_code || '91'
			form.api_key = ''
			form.api_secret = ''
			form.accounts = (workspace.hub_accounts || []).map((row) => ({ ...row }))
			const nextDiscoveryKey = `${form.hub_url}:${Boolean(
				workspace.transport?.credentials_configured,
			)}`
			if (
				props.canManage &&
				workspace.transport?.credentials_configured &&
				discoveryKey !== nextDiscoveryKey
			) {
				discoveryKey = nextDiscoveryKey
				loadHubAccounts({ silent: true })
			}
		},
		{ immediate: true },
	)

	function addAccount() {
		form.accounts.push({ channel: '', account_name: '', is_default: !form.accounts.length })
	}

	function removeAccount(index) {
		form.accounts.splice(index, 1)
	}

	async function loadHubAccounts({ silent = false } = {}) {
		if (loadingAccounts.value) return
		loadingAccounts.value = true
		try {
			hubAccounts.value = await call(
				'frappe_whatsapp_core.frontend_api.discover_hub_accounts',
			)
			if (!silent) {
				toast.add({
					severity: 'success',
					summary: 'Hub accounts refreshed',
					detail: `${hubAccounts.value.length} Integration account${hubAccounts.value.length === 1 ? '' : 's'} available.`,
					life: 3000,
				})
			}
		} catch (error) {
			if (!silent) {
				toast.add({
					severity: 'error',
					summary: 'Hub accounts unavailable',
					detail: errorMessage(error),
					life: 5000,
				})
			}
		} finally {
			loadingAccounts.value = false
		}
	}

	async function save() {
		form.saving = true
		try {
			const updated = await call('frappe_whatsapp_core.frontend_api.save_core_settings', {
				enabled: Number(form.enabled),
				outbound_enabled: Number(form.outbound_enabled),
				hub_url: form.hub_url,
				relay_url: form.relay_url,
				request_timeout: form.request_timeout,
				default_country_calling_code: form.default_country_calling_code,
				api_key: form.api_key,
				api_secret: form.api_secret,
				accounts: form.accounts,
			})
			emit('saved', updated)
			toast.add({
				severity: 'success',
				summary: 'Core transport saved',
				detail: form.relay_url
					? 'This workspace now sends directly through the durable Go relay.'
					: 'Operational sending remains disabled until a Go relay URL is configured.',
				life: 3000,
			})
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Transport not saved',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			form.saving = false
		}
	}
</script>

<template>
	<section class="surface-card transport-card">
		<header>
			<div>
				<div class="eyebrow">Core → Go runtime · Frappe management plane</div>
				<h2>Durable transport onboarding</h2>
				<p>Map local channels and keep Frappe outside the high-volume transport path.</p>
			</div>
			<span
				:class="[
					'transport-state',
					{ ready: workspace.transport?.credentials_configured },
				]"
			>
				<KeyRound :size="15" />
				{{
					workspace.transport?.credentials_configured
						? 'Credentials stored'
						: 'Credentials required'
				}}
			</span>
		</header>

		<form autocomplete="off" @submit.prevent="save">
			<div class="transport-form">
				<label class="switch-field">
					<ToggleSwitch v-model="form.enabled" :disabled="!canManage" />
					<span
						><strong>Enable WhatsApp Core</strong
						><small>Receive and operate WhatsApp in this workspace.</small></span
					>
				</label>
				<label class="switch-field">
					<ToggleSwitch v-model="form.outbound_enabled" :disabled="!canManage" />
					<span
						><strong>Enable outbound</strong
						><small>Allow UI, Flow Builder and MCP to queue messages.</small></span
					>
				</label>
				<label>
					<span>Integration Hub URL</span>
					<InputText
						v-model="form.hub_url"
						:disabled="!canManage"
						placeholder="https://whatsapp-hub.example.com"
					/>
				</label>
				<label>
					<span>Go relay URL</span>
					<InputText
						v-model="form.relay_url"
						:disabled="!canManage"
						placeholder="https://whatsapp-relay.example.com"
					/>
					<small>Outbound messages, read receipts, and typing bypass Frappe.</small>
				</label>
				<label>
					<span>Request timeout</span>
					<InputNumber
						v-model="form.request_timeout"
						:disabled="!canManage"
						:min="2"
						:max="120"
						suffix=" sec"
					/>
				</label>
				<label>
					<span>Default country calling code</span>
					<InputText
						v-model="form.default_country_calling_code"
						:disabled="!canManage"
						placeholder="91"
					/>
					<small
						>Only used for local numbers; + or 00 international numbers are
						preserved.</small
					>
				</label>
				<label>
					<span>Hub API key</span>
					<InputText
						v-model="form.api_key"
						:disabled="!canManage"
						name="whatsapp-hub-api-key"
						autocomplete="username"
						placeholder="Leave blank to preserve"
					/>
				</label>
				<label>
					<span>Hub API secret</span>
					<Password
						v-model="form.api_secret"
						:disabled="!canManage"
						:feedback="false"
						name="whatsapp-hub-api-secret"
						:input-props="{ autocomplete: 'current-password' }"
						toggle-mask
						placeholder="Leave blank to preserve"
					/>
				</label>
			</div>

			<div class="account-heading">
				<div>
					<strong>Channel mappings</strong
					><span>Local Core channel → central Hub account</span>
				</div>
				<div v-if="canManage" class="account-actions">
					<Button
						label="Refresh Hub accounts"
						text
						size="small"
						:loading="loadingAccounts"
						:disabled="!workspace.transport?.credentials_configured"
						@click="loadHubAccounts()"
					>
						<template #icon><RefreshCw :size="14" /></template>
					</Button>
					<Button label="Add mapping" text size="small" @click="addAccount">
						<template #icon><Plus :size="14" /></template>
					</Button>
				</div>
			</div>
			<div class="account-list">
				<div v-for="(account, index) in form.accounts" :key="index" class="account-row">
					<Select
						v-model="account.channel"
						:options="workspace.channels"
						option-label="display_name"
						option-value="name"
						:disabled="!canManage"
						placeholder="Local channel"
					/>
					<Select
						v-model="account.account_name"
						:options="hubAccountOptions"
						option-label="label"
						option-value="name"
						filter
						:disabled="!canManage"
						placeholder="Hub account"
					/>
					<label class="default-map"
						><ToggleSwitch v-model="account.is_default" :disabled="!canManage" /><span
							>Default</span
						></label
					>
					<Button
						v-if="canManage"
						text
						rounded
						severity="danger"
						aria-label="Remove mapping"
						@click="removeAccount(index)"
					>
						<Trash2 :size="15" />
					</Button>
				</div>
				<p v-if="!form.accounts.length" class="empty-copy">
					No channel is mapped to the Integration Hub yet.
				</p>
			</div>
			<footer v-if="canManage">
				<Button type="submit" label="Save transport" :loading="form.saving">
					<template #icon><Save :size="15" /></template>
				</Button>
			</footer>
		</form>
	</section>
</template>

<style scoped>
	.transport-card {
		margin-bottom: 16px;
		overflow: hidden;
	}
	header,
	.account-heading,
	footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 15px;
		padding: 17px 18px;
	}
	header,
	.account-heading {
		border-bottom: 1px solid var(--wa-border);
	}
	header h2 {
		margin: 3px 0 0;
		font-size: 15px;
	}
	header p {
		margin: 4px 0 0;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.transport-state {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 7px 10px;
		border-radius: 20px;
		color: var(--wa-warning);
		background: var(--wa-warning-soft);
		font-size: 12px;
		font-weight: 700;
	}
	.transport-state.ready {
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}
	.transport-form {
		padding: 17px 18px;
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
	}
	.transport-form > label {
		display: grid;
		gap: 6px;
		color: var(--wa-muted);
		font-size: 12px;
		font-weight: 700;
	}
	.transport-form :deep(input),
	.transport-form :deep(.p-password),
	.transport-form :deep(.p-inputnumber) {
		width: 100%;
	}
	.switch-field {
		display: flex !important;
		align-items: center;
		gap: 10px;
		padding: 10px;
		border: 1px solid var(--wa-border);
		border-radius: 11px;
	}
	.switch-field strong,
	.switch-field small {
		display: block;
	}
	.switch-field small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-weight: 400;
	}
	.account-heading strong,
	.account-heading span {
		display: block;
	}
	.account-actions {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-wrap: wrap;
		justify-content: flex-end;
	}
	.account-heading strong {
		font-size: 11px;
	}
	.account-heading span {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.account-list {
		padding: 12px 18px 17px;
		display: grid;
		gap: 9px;
	}
	.account-row {
		display: grid;
		grid-template-columns: minmax(160px, 1fr) minmax(180px, 1fr) 100px 36px;
		align-items: center;
		gap: 9px;
	}
	.default-map {
		display: flex;
		align-items: center;
		gap: 7px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	footer {
		justify-content: flex-end;
		border-top: 1px solid var(--wa-border);
	}
	@media (max-width: 760px) {
		header,
		.account-heading {
			align-items: flex-start;
			flex-direction: column;
		}
		.account-actions {
			width: 100%;
			justify-content: flex-start;
		}
		.transport-form {
			grid-template-columns: 1fr;
		}
		.account-row {
			grid-template-columns: 1fr;
		}
	}
</style>
