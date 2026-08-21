<script setup>
	import { computed, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import Textarea from 'primevue/textarea'
	import {
		ArrowDownLeft,
		ArrowUpRight,
		CheckCircle2,
		Clock3,
		History,
		Phone,
		PhoneCall,
		PhoneMissed,
		RefreshCw,
		Send,
		ShieldCheck,
		ShieldOff,
	} from 'lucide-vue-next'
	import AppDialog from '@/components/AppDialog.vue'
	import ChannelSelect from '@/features/channels/components/ChannelSelect.vue'
	import { normalizeCallPermission } from '@/features/calling/services/callPermission'
	import ContactSelect from '@/features/contacts/components/ContactSelect.vue'
	import { call, errorMessage } from '@/services/frappe'
	import { useCallingStore } from '@/stores/calling'
	import { formatDateTime, parseDateTime } from '@/utils/datetime'

	const calling = useCallingStore()
	const selectedIdentity = ref('')
	const action = ref('')
	const localError = ref('')
	const permission = ref(null)
	const invitationOpen = ref(false)
	const invitationText = ref('Call us on WhatsApp when it is convenient for you.')

	const selectedContact = computed(() =>
		calling.contacts.find((item) => item.identity === selectedIdentity.value),
	)
	const statusSeverity = computed(() =>
		calling.callingEnabled ? 'success' : calling.workspace.available ? 'warn' : 'danger',
	)
	const statusLabel = computed(() =>
		calling.callingEnabled
			? 'Ready to call'
			: calling.workspace.available
				? 'Calling not enabled'
				: 'Calling unavailable',
	)
	const visibleError = computed(() => {
		if (localError.value) return localError.value
		if (calling.workspace.available === false) return ''
		if (!calling.error) return ''
		return 'Calling is temporarily unavailable. Ask a WhatsApp Manager to check the Hub connection.'
	})
	const callingUnavailable = computed(
		() => !calling.loading && calling.workspace.available === false,
	)
	const unavailableTitle = computed(() =>
		calling.workspace.configured === false
			? 'Connect WhatsApp Integration to use calling'
			: 'WhatsApp calling is not available for this account',
	)
	const unavailableCopy = computed(
		() =>
			calling.error ||
			(calling.workspace.configured === false
				? 'Complete the Core-to-Hub connection first, then recheck availability.'
				: 'Meta has not made calling available for this phone number. Recheck after permissions or account settings change.'),
	)

	function statusLabelFor(callRow) {
		const value = String(callRow?.status || '').toLowerCase()
		return (
			{
				connect: callRow.direction === 'Inbound' ? 'Incoming' : 'Calling',
				pre_accept: 'Connecting',
				accept: 'Answered',
				accepted: 'Answered',
				terminate: 'Completed',
				terminated: 'Completed',
				ended: 'Completed',
				reject: 'Declined',
				rejected: 'Declined',
				missed: 'Missed',
				failed: 'Failed',
			}[value] || (value ? value.replaceAll('_', ' ') : 'Unknown')
		)
	}

	function statusSeverityFor(callRow) {
		const value = String(callRow?.status || '').toLowerCase()
		if (['accept', 'accepted', 'terminate', 'terminated', 'ended'].includes(value))
			return 'success'
		if (['reject', 'rejected', 'missed', 'failed'].includes(value)) return 'danger'
		return 'info'
	}

	function duration(callRow) {
		const start = parseDateTime(callRow?.started_at)
		const end = parseDateTime(callRow?.ended_at)
		if (!start || !end) return ''
		const seconds = Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000))
		if (seconds < 60) return `${seconds}s`
		return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
	}

	async function run(name, callback) {
		action.value = name
		localError.value = ''
		calling.clearMessages()
		try {
			return await callback()
		} catch (error) {
			localError.value = errorMessage(error)
			return null
		} finally {
			action.value = ''
		}
	}

	async function checkPermission() {
		permission.value = null
		if (!selectedIdentity.value) return
		const result = await run('permission', () =>
			call('frappe_whatsapp_core.calling.get_call_permission', {
				account_name: calling.selectedAccount,
				identity: selectedIdentity.value,
			}),
		)
		if (result) permission.value = normalizeCallPermission(result)
		return permission.value
	}

	async function startCall() {
		if (!selectedContact.value) return
		const currentPermission = permission.value || (await checkPermission())
		if (!currentPermission?.allowed) {
			localError.value =
				'This contact has not granted an active business-call permission. Send a call invitation first.'
			return
		}
		await run('start', () => calling.startCall(selectedContact.value))
	}

	async function sendInvitation() {
		if (!selectedIdentity.value || !invitationText.value.trim()) return
		const result = await run('invite', () =>
			call('frappe_whatsapp_core.calling.send_call_button', {
				account_name: calling.selectedAccount,
				identity: selectedIdentity.value,
				body_text: invitationText.value.trim(),
				display_text: 'Call Now',
			}),
		)
		if (result) {
			invitationOpen.value = false
			calling.notice = 'Call invitation sent.'
		}
	}

	async function openArtifact(callRow, kind) {
		const mediaId = callRow?.[`${kind}_media_id`]
		const localUrl = kind === 'recording' ? callRow?.recording_url : callRow?.transcript_url
		if (!mediaId && !localUrl) return
		const artifactKey = callRow?.name || mediaId
		const result = await run(`artifact-${artifactKey}`, () =>
			call('frappe_whatsapp_core.calling.get_call_artifact', {
				call_name: callRow.name,
				kind,
				download: 1,
			}),
		)
		if (result?.file_url) window.open(result.file_url, '_blank', 'noopener')
	}

	async function callAgain(callRow) {
		const contact = calling.contacts.find((item) => item.identity === callRow.remote_identity)
		if (!contact) {
			localError.value = 'This contact is no longer inside your calling scope.'
			return
		}
		selectedIdentity.value = contact.identity
		await startCall()
	}

	watch(selectedIdentity, () => {
		permission.value = null
	})
</script>

<template>
	<div class="calling-page">
		<header class="page-heading calling-heading">
			<div>
				<div class="eyebrow">WhatsApp Business Calling</div>
				<h1>Call customers from the workspace</h1>
				<p>Secure browser audio with the same team access rules as the shared inbox.</p>
			</div>
			<div class="heading-actions">
				<ChannelSelect
					:model-value="calling.selectedAccount"
					:options="calling.accounts"
					aria-label="WhatsApp account"
					:disabled="calling.loading || calling.busy"
					@update:model-value="calling.selectAccount($event)"
				/>
				<Tag :value="statusLabel" :severity="statusSeverity" rounded />
			</div>
		</header>

		<div v-if="visibleError" class="banner error-banner">
			{{ visibleError }}
		</div>
		<div v-if="calling.notice" class="banner success-banner">{{ calling.notice }}</div>

		<section v-if="callingUnavailable" class="surface-card availability-card" role="status">
			<span class="availability-icon"><ShieldOff :size="25" /></span>
			<div>
				<strong>{{ unavailableTitle }}</strong>
				<p>{{ unavailableCopy }}</p>
				<small>
					Availability is checked directly against Meta. Existing call history remains
					below.
				</small>
			</div>
			<Button
				label="Recheck availability"
				outlined
				:loading="calling.loading"
				@click="calling.load()"
			>
				<template #icon><RefreshCw :size="15" /></template>
			</Button>
		</section>

		<section
			v-else-if="!calling.callingEnabled && calling.workspace.available"
			class="surface-card activation-card"
		>
			<div class="feature-icon"><ShieldCheck :size="25" /></div>
			<div>
				<strong>Calling is ready to be activated</strong>
				<p>
					The supported WhatsApp calling defaults are applied automatically. Your team
					can start calling as soon as a manager enables it.
				</p>
			</div>
			<Button
				v-if="calling.canManage"
				label="Enable calling"
				icon="pi pi-check"
				:loading="action === 'enable'"
				@click="run('enable', () => calling.enableCalling())"
			/>
			<small v-else>Ask a WhatsApp Manager to enable calling once.</small>
		</section>

		<div v-if="!callingUnavailable" class="calling-grid">
			<section class="surface-card dialer-card">
				<div class="section-heading">
					<div class="feature-icon"><PhoneCall :size="23" /></div>
					<div>
						<h2>Start a call</h2>
						<p>Only contacts available to your team are shown.</p>
					</div>
				</div>
				<label class="field-label">
					Contact
					<ContactSelect
						v-model="selectedIdentity"
						:options="calling.contacts"
						placeholder="Search a contact by name or number"
						:disabled="!calling.callingEnabled || calling.busy"
					/>
				</label>
				<div v-if="selectedContact" class="selected-contact">
					<div class="contact-avatar">
						{{ (selectedContact.label || 'W').slice(0, 1).toUpperCase() }}
					</div>
					<div>
						<strong>{{ selectedContact.label }}</strong>
						<span>{{
							selectedContact.phone_number || selectedContact.reference
						}}</span>
					</div>
					<CheckCircle2 :size="20" />
				</div>
				<div v-if="permission" class="permission-result">
					<div>
						<small>Business-call permission</small>
						<strong>{{ permission.label }}</strong>
					</div>
					<span v-if="permission.expiresAt"
						>Until {{ formatDateTime(permission.expiresAt) }}</span
					>
				</div>
				<div class="dialer-actions">
					<Button
						label="Check permission"
						severity="secondary"
						outlined
						:disabled="!selectedIdentity"
						:loading="action === 'permission'"
						@click="checkPermission"
					/>
					<Button
						label="Invite to call"
						severity="secondary"
						outlined
						:disabled="!selectedIdentity || !calling.callingEnabled"
						@click="invitationOpen = true"
					/>
					<Button
						class="call-button"
						label="Call now"
						:disabled="!selectedIdentity || !calling.callingEnabled || calling.busy"
						:loading="action === 'start'"
						@click="startCall"
					>
						<template #icon><Phone :size="18" /></template>
					</Button>
				</div>
				<p class="privacy-note">
					Your browser requests microphone access only when you start or answer a call.
				</p>
			</section>

			<section class="surface-card readiness-card">
				<div class="section-heading compact">
					<div class="feature-icon"><ShieldCheck :size="21" /></div>
					<div>
						<h2>Private by design</h2>
						<p>Your team sees only the contacts and calls they can handle.</p>
					</div>
				</div>
				<ul>
					<li><CheckCircle2 :size="17" /> Team-scoped contacts and incoming calls</li>
					<li><CheckCircle2 :size="17" /> Secure browser voice calls</li>
					<li><CheckCircle2 :size="17" /> Announced call recording for every call</li>
					<li><CheckCircle2 :size="17" /> Global call controls while you work</li>
					<li><CheckCircle2 :size="17" /> Live ringing, answer and call status</li>
				</ul>
			</section>
		</div>

		<section class="surface-card history-card">
			<div class="section-heading history-heading">
				<div class="heading-copy">
					<div class="feature-icon"><History :size="22" /></div>
					<div>
						<h2>Recent calls</h2>
						<p>Your team-scoped call history.</p>
					</div>
				</div>
				<Button
					icon="pi pi-refresh"
					label="Refresh"
					severity="secondary"
					text
					:loading="calling.loading"
					@click="calling.load()"
				/>
			</div>
			<div v-if="calling.calls.length" class="call-list">
				<article
					v-for="callRow in calling.calls"
					:key="callRow.name || callRow.call_id"
					class="call-row"
				>
					<div class="contact-avatar small">
						{{ (callRow.display_name || 'W').slice(0, 1).toUpperCase() }}
					</div>
					<div class="call-person">
						<strong>{{ callRow.display_name }}</strong>
						<span>
							<ArrowDownLeft v-if="callRow.direction === 'Inbound'" :size="14" />
							<ArrowUpRight v-else :size="14" />
							{{ callRow.direction }} · {{ callRow.remote_number || 'WhatsApp' }}
						</span>
						<span v-if="callRow.handled_by_name" class="handled-by">
							Answered by {{ callRow.handled_by_name }}
						</span>
					</div>
					<div class="call-time">
						<strong>{{
							formatDateTime(callRow.started_at || callRow.modified)
						}}</strong>
						<span v-if="duration(callRow)"
							><Clock3 :size="13" />{{ duration(callRow) }}</span
						>
					</div>
					<Tag
						:value="statusLabelFor(callRow)"
						:severity="statusSeverityFor(callRow)"
						rounded
					/>
					<div class="row-actions">
						<Button
							v-if="callRow.recording_media_id || callRow.recording_url"
							label="Recording"
							severity="secondary"
							text
							:loading="
								action === `artifact-${callRow.name || callRow.recording_media_id}`
							"
							@click="openArtifact(callRow, 'recording')"
						/>
						<Button
							v-if="callRow.transcript_media_id"
							label="Transcript"
							severity="secondary"
							text
							:loading="action === `artifact-${callRow.transcript_media_id}`"
							@click="openArtifact(callRow, 'transcript')"
						/>
						<Button
							icon="pi pi-phone"
							aria-label="Call again"
							severity="secondary"
							text
							rounded
							:disabled="calling.busy || !callRow.remote_identity"
							@click="callAgain(callRow)"
						/>
					</div>
				</article>
				<div v-if="calling.workspace.calls_has_more" class="history-more">
					<Button
						label="Load more calls"
						severity="secondary"
						outlined
						:loading="calling.loadingMore"
						@click="calling.loadMoreCalls()"
					/>
				</div>
			</div>
			<div v-else class="empty-history">
				<PhoneMissed :size="28" />
				<strong>No calls yet</strong>
				<span>Your incoming and outgoing WhatsApp calls will appear here.</span>
			</div>
		</section>

		<AppDialog
			v-model:visible="invitationOpen"
			modal
			header="Invite this contact to call"
			:style="{ width: 'min(32rem, calc(100vw - 2rem))' }"
		>
			<div class="invitation-form">
				<p>Send a WhatsApp call button when a customer should initiate the call.</p>
				<Textarea v-model="invitationText" rows="4" fluid maxlength="1024" />
			</div>
			<template #footer>
				<Button
					label="Cancel"
					severity="secondary"
					outlined
					@click="invitationOpen = false"
				/>
				<Button
					label="Send invitation"
					:loading="action === 'invite'"
					:disabled="!invitationText.trim()"
					@click="sendInvitation"
				>
					<template #icon><Send :size="17" /></template>
				</Button>
			</template>
		</AppDialog>
	</div>
</template>

<style scoped>
	.calling-page {
		display: grid;
		gap: 18px;
	}
	.calling-heading {
		align-items: flex-start;
	}
	.calling-heading p {
		margin: 5px 0 0;
	}
	.eyebrow {
		color: var(--wa-primary);
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0.12em;
		text-transform: uppercase;
	}
	.heading-actions {
		display: flex;
		gap: 10px;
		align-items: center;
	}
	.heading-actions :deep(.p-select) {
		min-width: 220px;
	}
	.activation-card {
		padding: 18px;
		display: grid;
		grid-template-columns: 46px minmax(0, 1fr) auto;
		gap: 14px;
		align-items: center;
		border-color: color-mix(in srgb, var(--wa-primary) 35%, var(--wa-border));
	}
	.activation-card p,
	.activation-card small {
		margin: 4px 0 0;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.availability-card {
		display: grid;
		grid-template-columns: 46px minmax(0, 1fr) auto;
		align-items: center;
		gap: 15px;
		padding: 20px;
		border-color: color-mix(in srgb, var(--wa-warning) 28%, var(--wa-border));
		background: color-mix(in srgb, var(--wa-warning) 6%, var(--wa-surface));
	}
	.availability-icon {
		display: grid;
		place-items: center;
		width: 46px;
		height: 46px;
		border-radius: 14px;
		color: var(--wa-warning);
		background: color-mix(in srgb, var(--wa-warning) 13%, transparent);
	}
	.availability-card p,
	.availability-card small {
		display: block;
		margin: 4px 0 0;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.5;
	}
	.feature-icon {
		width: 42px;
		height: 42px;
		display: grid;
		place-items: center;
		border-radius: 12px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		flex: 0 0 42px;
	}
	.calling-grid {
		display: grid;
		grid-template-columns: minmax(0, 1.7fr) minmax(280px, 0.8fr);
		gap: 18px;
	}
	.dialer-card,
	.readiness-card,
	.history-card {
		padding: 20px;
	}
	.section-heading,
	.heading-copy {
		display: flex;
		gap: 12px;
		align-items: center;
	}
	.section-heading h2 {
		margin: 0;
		color: var(--wa-text);
		font-size: 16px;
	}
	.section-heading p {
		margin: 3px 0 0;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.field-label {
		margin-top: 22px;
		display: grid;
		gap: 8px;
		color: var(--wa-text);
		font-size: 12px;
		font-weight: 700;
	}
	.selected-contact {
		margin-top: 12px;
		padding: 12px;
		display: grid;
		grid-template-columns: 42px minmax(0, 1fr) 22px;
		gap: 10px;
		align-items: center;
		border: 1px solid var(--wa-border);
		border-radius: 12px;
		background: var(--wa-surface-muted);
	}
	.contact-avatar {
		width: 42px;
		height: 42px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		color: white;
		background: linear-gradient(135deg, var(--wa-primary), var(--wa-green));
		font-weight: 800;
	}
	.contact-avatar.small {
		width: 38px;
		height: 38px;
	}
	.selected-contact div:nth-child(2),
	.call-person {
		min-width: 0;
		display: grid;
		gap: 3px;
	}
	.selected-contact strong,
	.selected-contact span,
	.call-person strong,
	.call-person span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.selected-contact span,
	.call-person span {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.selected-contact > svg {
		color: var(--wa-success);
	}
	.permission-result {
		margin-top: 12px;
		padding: 10px 12px;
		display: flex;
		justify-content: space-between;
		gap: 10px;
		border-radius: 10px;
		background: var(--wa-primary-soft);
	}
	.permission-result div {
		display: grid;
	}
	.permission-result small,
	.permission-result span {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.permission-result strong {
		font-size: 12px;
		text-transform: capitalize;
	}
	.dialer-actions {
		margin-top: 18px;
		display: flex;
		flex-wrap: wrap;
		gap: 9px;
	}
	.call-button {
		margin-left: auto;
		background: var(--wa-green) !important;
		border-color: var(--wa-green) !important;
	}
	.privacy-note {
		margin: 14px 0 0;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.readiness-card ul {
		margin: 22px 0 0;
		padding: 0;
		display: grid;
		gap: 14px;
		list-style: none;
	}
	.readiness-card li {
		display: flex;
		gap: 9px;
		align-items: center;
		color: var(--wa-text);
		font-size: 12px;
	}
	.readiness-card li svg {
		color: var(--wa-success);
	}
	.history-heading {
		justify-content: space-between;
	}
	.call-list {
		margin: 17px -20px -20px;
	}
	.call-row {
		min-height: 70px;
		padding: 12px 20px;
		display: grid;
		grid-template-columns: 38px minmax(180px, 1.3fr) minmax(160px, 0.8fr) 100px auto;
		gap: 12px;
		align-items: center;
		border-top: 1px solid var(--wa-border-soft);
	}
	.call-person span,
	.call-time span {
		display: flex;
		gap: 5px;
		align-items: center;
	}
	.call-person .handled-by {
		color: var(--wa-primary);
		font-weight: 600;
	}
	.call-time {
		display: grid;
		gap: 3px;
	}
	.call-time strong {
		font-size: 11px;
		font-weight: 600;
	}
	.call-time span {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.row-actions {
		display: flex;
		justify-content: flex-end;
		align-items: center;
	}
	.history-more {
		padding: 16px 20px;
		display: flex;
		justify-content: center;
		border-top: 1px solid var(--wa-border-soft);
	}
	.empty-history {
		min-height: 180px;
		display: grid;
		place-items: center;
		align-content: center;
		gap: 7px;
		color: var(--wa-muted);
		text-align: center;
	}
	.empty-history strong {
		color: var(--wa-text);
	}
	.empty-history span {
		font-size: 12px;
	}
	.invitation-form {
		display: grid;
		gap: 12px;
	}
	.invitation-form p {
		margin: 0;
		color: var(--wa-muted);
		font-size: 12px;
	}
	@media (max-width: 980px) {
		.calling-grid {
			grid-template-columns: 1fr;
		}
		.call-row {
			grid-template-columns: 38px minmax(160px, 1fr) 100px auto;
		}
		.call-time {
			display: none;
		}
	}
	@media (max-width: 680px) {
		.calling-heading,
		.heading-actions {
			display: grid;
			width: 100%;
		}
		.activation-card {
			grid-template-columns: 42px 1fr;
		}
		.availability-card {
			grid-template-columns: 42px 1fr;
		}
		.activation-card > :last-child,
		.availability-card > :last-child {
			grid-column: 1 / -1;
		}
		.dialer-actions > * {
			width: 100%;
		}
		.call-button {
			margin-left: 0;
		}
		.call-row {
			grid-template-columns: 38px minmax(0, 1fr) auto;
		}
		.call-row > .p-tag {
			grid-column: 2;
			justify-self: start;
		}
		.row-actions {
			grid-column: 3;
			grid-row: 1 / span 2;
		}
	}
</style>
