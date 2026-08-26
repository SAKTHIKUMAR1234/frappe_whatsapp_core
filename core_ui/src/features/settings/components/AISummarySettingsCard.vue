<script setup>
	import { computed, reactive, watch } from 'vue'
	import Button from 'primevue/button'
	import InputNumber from 'primevue/inputnumber'
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import ToggleSwitch from 'primevue/toggleswitch'
	import { BrainCircuit, Save } from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'

	import { call, errorMessage } from '@/services/frappe'

	const props = defineProps({
		workspace: { type: Object, required: true },
		canManage: { type: Boolean, default: false },
	})
	const emit = defineEmits(['saved'])
	const toast = useToast()
	const form = reactive({
		enabled: false,
		action: '',
		batch_size: 100,
		max_media_mb: 15,
		saving: false,
	})
	const actionOptions = computed(() =>
		(props.workspace.i2a_actions || []).map((row) => ({
			...row,
			label: row.purpose
				? `${row.action_name || row.name} · ${row.purpose}`
				: row.action_name || row.name,
		})),
	)

	watch(
		() => props.workspace.ai_summary,
		(settings) => {
			form.enabled = Boolean(settings?.enabled)
			form.action = settings?.action || ''
			form.batch_size = settings?.batch_size || 100
			form.max_media_mb = settings?.max_media_mb || 15
		},
		{ immediate: true },
	)

	async function save() {
		form.saving = true
		try {
			const updated = await call(
				'frappe_whatsapp_core.frontend_api.save_ai_summary_settings',
				{
					enabled: Number(form.enabled),
					action: form.action,
					batch_size: form.batch_size,
					max_media_mb: form.max_media_mb,
				},
			)
			emit('saved', updated)
			toast.add({
				severity: 'success',
				summary: 'Message understanding saved',
				detail: 'New messages will be summarized incrementally through Frappe Tools.',
				life: 3500,
			})
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Message understanding not saved',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			form.saving = false
		}
	}
</script>

<template>
	<section class="surface-card ai-settings-card">
		<header>
			<div class="heading-copy">
				<span class="heading-icon"><BrainCircuit :size="18" /></span>
				<div>
					<h2>Message understanding</h2>
				</div>
			</div>
			<Tag
				:value="workspace.ai_summary?.configured ? 'Configured' : 'Needs I2A action'"
				:severity="workspace.ai_summary?.configured ? 'success' : 'warn'"
				rounded
			/>
		</header>

		<form @submit.prevent="save">
			<div class="ai-settings-form">
				<label class="switch-field">
					<ToggleSwitch v-model="form.enabled" :disabled="!canManage" />
					<strong>Enable 30-minute summary batches</strong>
				</label>
				<label class="action-field">
					<span>I2A action</span>
					<Select
						v-model="form.action"
						:options="actionOptions"
						option-label="label"
						option-value="name"
						:disabled="!canManage"
						placeholder="Select a Frappe Tools action"
						filter
					/>
					<small v-if="!actionOptions.length">
						Create an enabled I2A Action with one orchestrator model in Frappe Tools
						first.
					</small>
				</label>
				<label>
					<span>Messages per pass</span>
					<InputNumber
						v-model="form.batch_size"
						:disabled="!canManage"
						:min="1"
						:max="250"
					/>
				</label>
				<label>
					<span>Maximum media size</span>
					<InputNumber
						v-model="form.max_media_mb"
						:disabled="!canManage"
						:min="1"
						:max="50"
						suffix=" MB"
					/>
				</label>
			</div>
			<footer v-if="canManage">
				<Button
					type="submit"
					label="Save message understanding"
					:loading="form.saving"
					:disabled="form.enabled && !form.action"
				>
					<template #icon><Save :size="15" /></template>
				</Button>
			</footer>
		</form>
	</section>
</template>

<style scoped>
	.ai-settings-card {
		margin-bottom: 16px;
		overflow: hidden;
	}
	header,
	footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 15px;
		padding: 17px 18px;
	}
	header {
		border-bottom: 1px solid var(--wa-border);
	}
	.heading-copy,
	.switch-field {
		display: flex;
		align-items: center;
		gap: 11px;
	}
	.heading-icon {
		display: grid;
		width: 38px;
		height: 38px;
		place-items: center;
		border-radius: 11px;
		background: var(--wa-primary-soft);
		color: var(--wa-primary);
	}
	h2 {
		margin: 3px 0 0;
		font-size: 15px;
	}
	header p {
		margin: 4px 0 0;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.ai-settings-form {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
		padding: 17px 18px;
	}
	.ai-settings-form > label {
		display: grid;
		min-width: 0;
		gap: 6px;
		font-size: 12px;
		font-weight: 700;
	}
	.ai-settings-form :deep(.p-select),
	.ai-settings-form :deep(.p-inputnumber),
	.ai-settings-form :deep(.p-inputnumber-input) {
		width: 100%;
		min-width: 0;
	}
	.switch-field {
		grid-column: 1 / -1;
		justify-content: flex-start;
	}
	.switch-field > span {
		display: grid;
		gap: 2px;
	}
	.ai-settings-form small {
		color: var(--wa-muted);
		font-size: 11px;
		font-weight: 500;
	}
	footer {
		justify-content: flex-end;
		border-top: 1px solid var(--wa-border);
	}
	@media (max-width: 720px) {
		header {
			align-items: flex-start;
			flex-direction: column;
		}
		.ai-settings-form {
			grid-template-columns: 1fr;
		}
		.switch-field {
			grid-column: auto;
		}
	}
</style>
