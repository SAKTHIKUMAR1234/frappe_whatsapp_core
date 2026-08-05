<script setup>
	import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import { useToast } from 'primevue/usetoast'
	import { MessageSquarePlus, RefreshCw, Search, Send, ShieldAlert } from 'lucide-vue-next'

	import ConversationContext from '@/features/inbox/components/ConversationContext.vue'
	import ConversationList from '@/features/inbox/components/ConversationList.vue'
	import MessageBubble from '@/features/inbox/components/MessageBubble.vue'
	import { call } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'

	const route = useRoute()
	const router = useRouter()
	const toast = useToast()
	const session = useSessionStore()
	const loading = ref(true)
	const detailLoading = ref(false)
	const loadingOlder = ref(false)
	const sending = ref(false)
	const search = ref('')
	const rows = ref([])
	const detail = ref(null)
	const messagePage = ref({ has_more: false })
	const draft = ref('')
	const stream = ref(null)
	const newDialog = ref(false)
	const starting = ref(false)
	const catalog = ref({ templates: [] })
	const settings = ref({ channels: [] })
	const newChat = ref({ channel: '', phone_number: '', display_name: '', template: '' })
	const unsubscribers = []

	const selectedName = computed(() => route.params.conversation || '')
	const filteredRows = computed(() => {
		const query = search.value.trim().toLowerCase()
		if (!query) return rows.value
		return rows.value.filter((row) =>
			[
				row.display_name,
				row.phone_number,
				row.party_binding?.party_name,
				row.party_binding?.party_role,
				row.latest_message?.body,
			]
				.join(' ')
				.toLowerCase()
				.includes(query),
		)
	})
	const messageMap = computed(
		() => new Map((detail.value?.messages || []).map((message) => [message.name, message])),
	)
	const topics = computed(() =>
		(detail.value?.topics || []).map((topic) => ({
			...topic,
			messageRows: (topic.messages || [])
				.map((messageName) => messageMap.value.get(messageName))
				.filter(Boolean),
		})),
	)
	const assignedMessages = computed(
		() => new Set(topics.value.flatMap((topic) => topic.messages || [])),
	)
	const ungrouped = computed(() =>
		(detail.value?.messages || []).filter(
			(message) => !assignedMessages.value.has(message.name),
		),
	)
	const textReady = computed(() => Boolean(detail.value?.outbound?.text_ready))

	async function loadRows() {
		loading.value = true
		try {
			rows.value = await call('frappe_whatsapp_core.inbox.conversations', { limit: 500 })
			if (!selectedName.value && rows.value.length) selectConversation(rows.value[0].name)
		} finally {
			loading.value = false
		}
	}

	async function loadDetail(name) {
		if (!name) {
			detail.value = null
			return
		}
		detailLoading.value = true
		try {
			detail.value = await call('frappe_whatsapp_core.inbox.conversation', { name })
			messagePage.value = detail.value.message_page || { has_more: false }
			const latest = detail.value.messages.at(-1)?.name
			if (latest) {
				await call('frappe_whatsapp_core.inbox.read_conversation', {
					name,
					message: latest,
				})
				const row = rows.value.find((item) => item.name === name)
				if (row) row.unread_count = 0
			}
			await scrollToBottom()
		} finally {
			detailLoading.value = false
		}
	}

	async function loadOlderMessages() {
		if (!detail.value || !messagePage.value.has_more || loadingOlder.value || !stream.value)
			return
		loadingOlder.value = true
		const previousHeight = stream.value.scrollHeight
		try {
			const page = await call('frappe_whatsapp_core.workspace_api.list_messages', {
				conversation: selectedName.value,
				before: messagePage.value.next_before,
				before_creation: messagePage.value.next_before_creation,
				limit: 50,
			})
			const known = new Set(detail.value.messages.map((message) => message.name))
			const older = [...page.rows].reverse().filter((message) => !known.has(message.name))
			detail.value.messages.unshift(...older)
			messagePage.value = page
			await nextTick()
			stream.value.scrollTop = stream.value.scrollHeight - previousHeight
		} finally {
			loadingOlder.value = false
		}
	}

	function handleStreamScroll() {
		if (stream.value?.scrollTop <= 64) loadOlderMessages()
	}

	function selectConversation(name) {
		router.replace({ name: 'inbox', params: { conversation: name } })
	}

	async function sendText() {
		const body = draft.value.trim()
		if (!body || !textReady.value) return
		sending.value = true
		draft.value = ''
		try {
			const message = await call('frappe_whatsapp_core.outbound.queue_text', {
				conversation_name: selectedName.value,
				body,
			})
			appendMessage({ conversation: selectedName.value, message })
		} catch (error) {
			draft.value = body
			toast.add({
				severity: 'error',
				summary: 'Message not queued',
				detail: apiError(error),
				life: 5000,
			})
		} finally {
			sending.value = false
		}
	}

	async function sendTemplate(templateName) {
		if (!templateName) return
		sending.value = true
		try {
			const message = await call('frappe_whatsapp_core.outbound.queue_template', {
				conversation_name: selectedName.value,
				template: templateName,
			})
			appendMessage({ conversation: selectedName.value, message })
		} finally {
			sending.value = false
		}
	}

	async function startConversation() {
		starting.value = true
		try {
			const started = await call('frappe_whatsapp_core.outbound.start_conversation', {
				channel: newChat.value.channel,
				phone_number: newChat.value.phone_number,
				display_name: newChat.value.display_name,
			})
			await call('frappe_whatsapp_core.outbound.queue_template', {
				conversation_name: started.conversation,
				template: newChat.value.template,
			})
			newDialog.value = false
			newChat.value = { channel: '', phone_number: '', display_name: '', template: '' }
			await loadRows()
			selectConversation(started.conversation)
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Conversation not started',
				detail: apiError(error),
				life: 5000,
			})
		} finally {
			starting.value = false
		}
	}

	async function openNewChat() {
		const [templateData, settingsData] = await Promise.all([
			call('frappe_whatsapp_core.frontend_api.template_catalog'),
			call('frappe_whatsapp_core.frontend_api.settings_workspace'),
		])
		catalog.value = templateData
		settings.value = settingsData
		newChat.value.channel =
			settingsData.channels.find((channel) => channel.enabled)?.name || ''
		newChat.value.template =
			templateData.templates.find(
				(template) => template.enabled && template.approval_status === 'APPROVED',
			)?.name || ''
		newDialog.value = true
	}

	function appendMessage(event) {
		if (!event?.conversation || !event.message) return
		if (event.conversation === selectedName.value && detail.value) {
			if (!detail.value.messages.some((message) => message.name === event.message.name)) {
				detail.value.messages.push(event.message)
				scrollToBottom()
			}
		}
		const row = rows.value.find((item) => item.name === event.conversation)
		if (row) {
			row.latest_message = event.message
			row.last_message_at = event.message.provider_timestamp
			if (
				event.message.direction === 'Inbound' &&
				event.conversation !== selectedName.value
			) {
				row.unread_count = Number(row.unread_count || 0) + 1
			}
		} else {
			loadRows()
		}
	}

	function updateMessageStatus(event) {
		if (event?.conversation !== selectedName.value || !detail.value) return
		const message = detail.value.messages.find((item) => item.name === event.message)
		if (message) {
			message.delivery_status = event.delivery_status
			message.provider_message_id = event.provider_message_id || message.provider_message_id
		}
	}

	async function updateStatus(status) {
		await call('frappe_whatsapp_core.inbox.update_conversation', {
			name: selectedName.value,
			status,
		})
		detail.value.conversation.status = status
		const row = rows.value.find((item) => item.name === selectedName.value)
		if (row) row.status = status
	}

	async function scrollToBottom() {
		await nextTick()
		if (stream.value) stream.value.scrollTop = stream.value.scrollHeight
	}

	function apiError(error) {
		return error?.response?.data?.exception || error?.message || 'Unexpected server error'
	}

	watch(selectedName, loadDetail)
	onMounted(async () => {
		await loadRows()
		if (selectedName.value) await loadDetail(selectedName.value)
		const site = session.boot?.site
		unsubscribers.push(
			subscribe(site, 'whatsapp_core_message', appendMessage),
			subscribe(site, 'whatsapp_core_message_status', updateMessageStatus),
		)
	})
	onBeforeUnmount(() => unsubscribers.forEach((unsubscribe) => unsubscribe()))
</script>

<template>
	<div class="inbox-page">
		<header class="inbox-heading">
			<div>
				<div class="eyebrow">Site-wide WhatsApp</div>
				<h1>Shared Inbox</h1>
				<p>Instant local updates with durable delivery through the Go relay.</p>
			</div>
			<div class="heading-actions">
				<Button outlined aria-label="Refresh" @click="loadRows"
					><RefreshCw :size="16"
				/></Button>
				<Button label="New chat" @click="openNewChat">
					<template #icon><MessageSquarePlus :size="16" /></template>
				</Button>
			</div>
		</header>

		<section class="inbox-workbench surface-card">
			<aside class="list-panel">
				<label class="conversation-search">
					<Search :size="16" />
					<InputText v-model="search" placeholder="Search people or messages" />
				</label>
				<div v-if="loading" class="loading-state">Loading conversations…</div>
				<ConversationList
					v-else
					:rows="filteredRows"
					:selected="selectedName"
					@select="selectConversation"
				/>
			</aside>

			<main class="chat-panel">
				<div v-if="detailLoading" class="empty-chat">Loading conversation…</div>
				<div v-else-if="!detail" class="empty-chat">
					<MessageSquarePlus :size="38" />
					<strong>Select or start a conversation</strong>
					<span
						>Core works independently; no company-specific frontend is required.</span
					>
				</div>
				<template v-else>
					<header class="chat-heading">
						<div>
							<strong>{{ detail.display_name }}</strong>
							<span>{{ detail.identity.normalized_value }}</span>
						</div>
						<span>{{ detail.conversation.status }}</span>
					</header>
					<div ref="stream" class="message-stream" @scroll.passive="handleStreamScroll">
						<div v-if="loadingOlder" class="older-loading">
							Loading older messages…
						</div>
						<button
							v-else-if="messagePage.has_more"
							class="older-loading older-button"
							type="button"
							@click="loadOlderMessages"
						>
							Load older messages
						</button>
						<details v-for="topic in topics" :key="topic.name" class="topic-group">
							<summary>
								<span>
									<small>{{ topic.category || 'AI topic' }}</small>
									<strong>{{ topic.title }}</strong>
									<p>
										{{ topic.summary || 'Open to review grouped messages.' }}
									</p>
								</span>
								<em>{{ topic.message_count }} messages</em>
							</summary>
							<div class="topic-messages">
								<MessageBubble
									v-for="message in topic.messageRows"
									:key="message.name"
									:message="message"
								/>
							</div>
						</details>
						<div v-if="ungrouped.length" class="ungrouped">
							<div v-if="topics.length" class="section-label">
								Recent ungrouped messages
							</div>
							<MessageBubble
								v-for="message in ungrouped"
								:key="message.name"
								:message="message"
							/>
						</div>
					</div>
					<footer v-if="textReady" class="composer">
						<Textarea
							v-model="draft"
							auto-resize
							rows="1"
							placeholder="Write a message"
							@keydown.enter.exact.prevent="sendText"
						/>
						<Button
							:disabled="!draft.trim()"
							:loading="sending"
							rounded
							@click="sendText"
						>
							<Send :size="18" />
						</Button>
					</footer>
					<footer v-else class="template-gate">
						<ShieldAlert :size="18" />
						<div>
							<strong>Template required</strong>
							<span>{{
								detail.outbound.reasons?.join(' · ') ||
								'The 24-hour service window is closed.'
							}}</span>
						</div>
						<Select
							:options="detail.templates"
							option-label="template_name"
							option-value="name"
							placeholder="Send approved template"
							@change="sendTemplate($event.value)"
						/>
					</footer>
				</template>
			</main>

			<ConversationContext v-if="detail" :data="detail" @status="updateStatus" />
			<aside v-else class="context-placeholder"></aside>
		</section>

		<Dialog
			v-model:visible="newDialog"
			modal
			header="Start WhatsApp conversation"
			class="new-chat-dialog"
		>
			<div class="dialog-form">
				<label
					>Channel<Select
						v-model="newChat.channel"
						:options="settings.channels.filter((item) => item.enabled)"
						option-label="display_name"
						option-value="name"
				/></label>
				<label
					>International phone<InputText
						v-model="newChat.phone_number"
						placeholder="919876543210"
				/></label>
				<label
					>Display name<InputText v-model="newChat.display_name" placeholder="Optional"
				/></label>
				<label
					>Approved opening template<Select
						v-model="newChat.template"
						:options="
							catalog.templates.filter(
								(item) => item.enabled && item.approval_status === 'APPROVED',
							)
						"
						option-label="template_name"
						option-value="name"
				/></label>
			</div>
			<template #footer>
				<Button label="Cancel" text @click="newDialog = false" />
				<Button
					label="Start and queue"
					:loading="starting"
					:disabled="!newChat.channel || !newChat.phone_number || !newChat.template"
					@click="startConversation"
				/>
			</template>
		</Dialog>
	</div>
</template>

<style scoped>
	.inbox-page {
		height: calc(100vh - 68px);
		padding: 22px 26px 26px;
		display: flex;
		flex-direction: column;
	}
	.inbox-heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 18px;
		margin-bottom: 16px;
	}
	.inbox-heading h1 {
		margin: 3px 0 0;
		font-size: 25px;
	}
	.inbox-heading p {
		margin: 4px 0 0;
		color: #718078;
		font-size: 11px;
	}
	.heading-actions {
		display: flex;
		gap: 8px;
	}
	.inbox-workbench {
		min-height: 0;
		flex: 1;
		display: grid;
		grid-template-columns: minmax(260px, 30%) minmax(420px, 1fr) minmax(210px, 25%);
		overflow: hidden;
	}
	.list-panel,
	.chat-panel {
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.list-panel {
		border-right: 1px solid #e2e9e5;
	}
	.conversation-search {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 11px 12px;
		border-bottom: 1px solid #e2e9e5;
		color: #819087;
		background: #fbfcfb;
	}
	.conversation-search :deep(input) {
		width: 100%;
		border: 0;
		box-shadow: none;
		background: transparent;
		font-size: 11px;
	}
	.loading-state,
	.empty-chat {
		flex: 1;
		display: grid;
		place-content: center;
		justify-items: center;
		gap: 8px;
		color: #7b8982;
		font-size: 11px;
	}
	.empty-chat strong {
		color: #34443d;
		font-size: 13px;
	}
	.empty-chat span {
		max-width: 310px;
		text-align: center;
		line-height: 1.5;
	}
	.chat-heading {
		height: 62px;
		padding: 11px 16px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		border-bottom: 1px solid #e2e9e5;
		background: #fbfcfb;
	}
	.chat-heading strong,
	.chat-heading span {
		display: block;
	}
	.chat-heading strong {
		font-size: 12px;
	}
	.chat-heading span {
		margin-top: 3px;
		color: #7a8981;
		font-size: 9px;
	}
	.message-stream {
		min-height: 0;
		flex: 1;
		padding: 18px;
		overflow-y: auto;
		background-color: #f2f6f3;
		background-image: radial-gradient(#dce8e1 0.7px, transparent 0.7px);
		background-size: 14px 14px;
	}
	.ungrouped,
	.topic-messages {
		display: grid;
		gap: 8px;
	}
	.section-label {
		margin: 8px 0;
		color: #6d7d75;
		font-size: 9px;
		text-align: center;
		text-transform: uppercase;
	}
	.older-loading {
		display: block;
		width: fit-content;
		margin: 0 auto 12px;
		padding: 5px 10px;
		border: 0;
		border-radius: 999px;
		color: #60726a;
		background: rgba(255, 255, 255, 0.92);
		font: inherit;
		font-size: 9px;
	}
	.older-button {
		cursor: pointer;
	}
	.topic-group {
		margin-bottom: 12px;
		border: 1px solid #d7e4dd;
		border-radius: 13px;
		background: rgba(255, 255, 255, 0.94);
	}
	.topic-group summary {
		padding: 11px 13px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		cursor: pointer;
	}
	.topic-group summary span > * {
		display: block;
	}
	.topic-group small,
	.topic-group em {
		color: #17805f;
		font-size: 8px;
		font-style: normal;
		text-transform: uppercase;
	}
	.topic-group strong {
		margin-top: 2px;
		font-size: 11px;
	}
	.topic-group p {
		margin: 3px 0 0;
		color: #6f7d76;
		font-size: 9px;
	}
	.topic-messages {
		padding: 12px;
		border-top: 1px solid #e5ece8;
	}
	.composer,
	.template-gate {
		padding: 10px 12px;
		display: flex;
		align-items: center;
		gap: 9px;
		border-top: 1px solid #dfe7e2;
		background: #fff;
	}
	.composer :deep(textarea) {
		flex: 1;
		max-height: 110px;
	}
	.template-gate {
		color: #a56314;
		background: #fff9ed;
	}
	.template-gate div {
		min-width: 0;
		flex: 1;
	}
	.template-gate strong,
	.template-gate span {
		display: block;
	}
	.template-gate strong {
		font-size: 10px;
	}
	.template-gate span {
		margin-top: 2px;
		color: #927344;
		font-size: 8px;
	}
	.context-placeholder {
		background: #fbfcfb;
	}
	.dialog-form {
		width: min(480px, 80vw);
		display: grid;
		gap: 14px;
	}
	.dialog-form label {
		display: grid;
		gap: 6px;
		color: #53635b;
		font-size: 10px;
		font-weight: 700;
	}
	.dialog-form :deep(.p-select),
	.dialog-form :deep(input) {
		width: 100%;
	}
	@media (max-width: 1120px) {
		.inbox-workbench {
			grid-template-columns: minmax(250px, 34%) 1fr;
		}
		.inbox-workbench > :deep(.context-panel),
		.context-placeholder {
			display: none;
		}
	}
	@media (max-width: 760px) {
		.inbox-page {
			padding: 14px;
		}
		.inbox-workbench {
			grid-template-columns: 1fr;
		}
		.list-panel {
			display: none;
		}
	}
</style>
