<script setup>
	import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import { useToast } from 'primevue/usetoast'
	import {
		MessageSquarePlus,
		Paperclip,
		ChevronLeft,
		RefreshCw,
		Search,
		Send,
		ShieldAlert,
		Smile,
		X,
	} from 'lucide-vue-next'

	import ConversationContext from '@/features/inbox/components/ConversationContext.vue'
	import ConversationList from '@/features/inbox/components/ConversationList.vue'
	import MessageBubble from '@/features/inbox/components/MessageBubble.vue'
	import { call, errorMessage, uploadFile } from '@/services/frappe'
	import { subscribe } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'

	const route = useRoute()
	const router = useRouter()
	const toast = useToast()
	const session = useSessionStore()
	const canManage = computed(() => Boolean(session.boot?.can_manage))
	const loading = ref(true)
	const detailLoading = ref(false)
	const loadingOlder = ref(false)
	const richSending = ref(false)
	const search = ref('')
	const rows = ref([])
	const listScrollTop = ref(Number(sessionStorage.getItem('whatsapp:inbox-scroll') || 0))
	const detail = ref(null)
	const messagePage = ref({ has_more: false })
	const messageSearchOpen = ref(false)
	const messageSearch = ref('')
	const messageSearchRows = ref([])
	const messageSearching = ref(false)
	const draft = ref('')
	const replyTo = ref(null)
	const richDialog = ref(false)
	const uploadingMedia = ref(false)
	const richForm = ref({
		type: 'image',
		media: '',
		caption: '',
		emoji: '👍',
		latitude: '',
		longitude: '',
		name: '',
		address: '',
		contacts: '[{"name":{"formatted_name":""},"phones":[{"phone":""}]}]',
		flow_id: '',
		flow_token: '',
		flow_cta: 'Open',
		flow_screen: '',
		flow_body: '',
	})
	const richTypes = [
		{ label: 'Image', value: 'image' },
		{ label: 'Video', value: 'video' },
		{ label: 'Audio', value: 'audio' },
		{ label: 'Document', value: 'document' },
		{ label: 'Sticker', value: 'sticker' },
		{ label: 'Reaction', value: 'reaction' },
		{ label: 'Location', value: 'location' },
		{ label: 'Contact', value: 'contacts' },
		{ label: 'Meta Flow', value: 'interactive' },
	]
	let typingSentAt = 0
	let messageSearchTimer = null
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
		if (name === selectedName.value) return
		router.push({
			name: 'inbox',
			params: { conversation: name },
			state: { fromInbox: true },
		})
	}

	function closeMobileConversation() {
		if (window.history.state?.fromInbox) router.back()
		else router.replace({ name: 'inbox' })
	}

	function rememberListScroll(value) {
		listScrollTop.value = value
		sessionStorage.setItem('whatsapp:inbox-scroll', String(value))
	}

	async function runMessageSearch() {
		const query = messageSearch.value.trim()
		if (!query || !selectedName.value) {
			messageSearchRows.value = []
			return
		}
		messageSearching.value = true
		try {
			const result = await call('frappe_whatsapp_core.workspace_api.list_messages', {
				conversation: selectedName.value,
				search: query,
				limit: 100,
			})
			messageSearchRows.value = [...result.rows].reverse()
		} finally {
			messageSearching.value = false
		}
	}

	function closeMessageSearch() {
		messageSearchOpen.value = false
		messageSearch.value = ''
		messageSearchRows.value = []
	}

	function newClientMessageId() {
		if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
		return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (character) => {
			const value = Math.floor(Math.random() * 16)
			const nibble = character === 'x' ? value : (value & 0x3) | 0x8
			return nibble.toString(16)
		})
	}

	function optimisticText(body, contextMessageId = '') {
		const clientMessageId = newClientMessageId()
		return {
			name: `optimistic:${clientMessageId}`,
			provider_message_id: `local:${clientMessageId}`,
			direction: 'Outbound',
			message_type: 'text',
			body,
			content: { context_message_id: contextMessageId },
			provider_timestamp: new Date().toISOString(),
			delivery_status: 'Queued',
			client_message_id: clientMessageId,
			optimistic: true,
		}
	}

	function reconcileMessage(message) {
		if (!detail.value || !message) return
		const index = detail.value.messages.findIndex(
			(item) =>
				item.name === message.name ||
				(item.provider_message_id &&
					item.provider_message_id === message.provider_message_id),
		)
		if (index >= 0) detail.value.messages.splice(index, 1, message)
		else detail.value.messages.push(message)
	}

	async function queueText(body, contextMessageId = '') {
		const optimistic = optimisticText(body, contextMessageId)
		reconcileMessage(optimistic)
		scrollToBottom()
		try {
			const message = await call('frappe_whatsapp_core.outbound.queue_text', {
				conversation_name: selectedName.value,
				body,
				context_message_id: contextMessageId,
				client_message_id: optimistic.client_message_id,
			})
			reconcileMessage(message)
			return message
		} catch (error) {
			optimistic.delivery_status = 'Failed'
			optimistic.failure = { error: errorMessage(error) }
			optimistic.optimistic = false
			toast.add({
				severity: 'error',
				summary: 'Message not queued',
				detail: errorMessage(error),
				life: 5000,
			})
			return null
		}
	}

	async function sendText() {
		const body = draft.value.trim()
		if (!body || !textReady.value) return
		const contextMessageId = replyTo.value?.provider_message_id || ''
		draft.value = ''
		replyTo.value = null
		await queueText(body, contextMessageId)
	}

	async function retryMessage(message) {
		if (message.message_type !== 'text') return
		await queueText(message.body || '')
	}

	function selectReply(message) {
		replyTo.value = message
	}

	async function toggleBookmark(message) {
		const result = await call('frappe_whatsapp_core.inbox.toggle_message_bookmark', {
			message: message.name,
		})
		message.bookmarked = result.bookmarked
	}

	async function showTyping() {
		const current = Date.now()
		if (!selectedName.value || current - typingSentAt < 25000) return
		typingSentAt = current
		try {
			await call('frappe_whatsapp_core.conversation_reads.show_typing', {
				conversation: selectedName.value,
			})
		} catch {
			// Typing state is transient and must never interrupt composing.
		}
	}

	function addEmoji() {
		draft.value += '😊'
		showTyping()
	}

	function richPayload() {
		const type = richForm.value.type
		const context_message_id = replyTo.value?.provider_message_id || ''
		if (['image', 'video', 'audio', 'document', 'sticker'].includes(type)) {
			const media = richForm.value.media.trim()
			const payload = {
				[media.startsWith('http://') || media.startsWith('https://') ? 'link' : 'id']:
					media,
				context_message_id,
			}
			if (type !== 'sticker' && richForm.value.caption.trim()) {
				payload.caption = richForm.value.caption.trim()
			}
			return payload
		}
		if (type === 'reaction') {
			return {
				message_id: replyTo.value?.provider_message_id || '',
				emoji: richForm.value.emoji,
			}
		}
		if (type === 'location') {
			return {
				latitude: richForm.value.latitude,
				longitude: richForm.value.longitude,
				name: richForm.value.name,
				address: richForm.value.address,
				context_message_id,
			}
		}
		if (type === 'contacts') {
			return { contacts: JSON.parse(richForm.value.contacts), context_message_id }
		}
		return {
			type: 'flow',
			body: { text: richForm.value.flow_body || 'Please complete this form.' },
			action: {
				name: 'flow',
				parameters: {
					flow_message_version: '3',
					flow_id: richForm.value.flow_id,
					flow_token: richForm.value.flow_token,
					flow_cta: richForm.value.flow_cta || 'Open',
					flow_action: 'navigate',
					flow_action_payload: {
						screen: richForm.value.flow_screen,
						data: {},
					},
				},
			},
			context_message_id,
		}
	}

	async function uploadMedia(event) {
		const file = event.target.files?.[0]
		if (!file) return
		uploadingMedia.value = true
		try {
			const stored = await uploadFile(file, true)
			const uploaded = await call('frappe_whatsapp_core.outbound.upload_media', {
				conversation_name: selectedName.value,
				file_url: stored.file_url,
			})
			richForm.value.media = uploaded.media_id
			toast.add({
				severity: 'success',
				summary: 'Media ready',
				detail: `${uploaded.filename} was uploaded to Meta.`,
				life: 3000,
			})
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Media upload failed',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			uploadingMedia.value = false
			event.target.value = ''
		}
	}

	async function sendRich() {
		let payload
		try {
			payload = richPayload()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Invalid message details',
				detail: errorMessage(error),
				life: 5000,
			})
			return
		}
		const type = richForm.value.type
		const optimistic = optimisticText(
			richForm.value.caption.trim() || richForm.value.flow_body.trim() || `[${type}]`,
		)
		optimistic.message_type = type
		optimistic.content = { payload }
		reconcileMessage(optimistic)
		scrollToBottom()
		richDialog.value = false
		replyTo.value = null
		try {
			const message = await call('frappe_whatsapp_core.outbound.queue_rich', {
				conversation_name: selectedName.value,
				message_type: type,
				payload,
				client_message_id: optimistic.client_message_id,
			})
			reconcileMessage(message)
		} catch (error) {
			optimistic.delivery_status = 'Failed'
			optimistic.failure = { error: errorMessage(error) }
			optimistic.optimistic = false
			toast.add({
				severity: 'error',
				summary: 'Message not queued',
				detail: errorMessage(error),
				life: 5000,
			})
		}
	}

	async function sendTemplate(templateName) {
		if (!templateName) return
		richSending.value = true
		try {
			const message = await call('frappe_whatsapp_core.outbound.queue_template', {
				conversation_name: selectedName.value,
				template: templateName,
			})
			appendMessage({ conversation: selectedName.value, message })
		} finally {
			richSending.value = false
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
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			starting.value = false
		}
	}

	async function openNewChat() {
		if (!canManage.value) return
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
			reconcileMessage(event.message)
			scrollToBottom()
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

	watch(selectedName, loadDetail)
	watch(selectedName, () => {
		replyTo.value = null
		typingSentAt = 0
		closeMessageSearch()
	})
	watch(messageSearch, () => {
		clearTimeout(messageSearchTimer)
		messageSearchTimer = setTimeout(runMessageSearch, 300)
	})
	onMounted(async () => {
		await loadRows()
		if (selectedName.value) await loadDetail(selectedName.value)
		const site = session.boot?.site
		unsubscribers.push(
			subscribe(site, 'whatsapp_core_message', appendMessage),
			subscribe(site, 'whatsapp_core_message_status', updateMessageStatus),
		)
	})
	onBeforeUnmount(() => {
		clearTimeout(messageSearchTimer)
		unsubscribers.forEach((unsubscribe) => unsubscribe())
	})
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
				<Button v-if="canManage" label="New chat" @click="openNewChat">
					<template #icon><MessageSquarePlus :size="16" /></template>
				</Button>
			</div>
		</header>

		<section :class="['inbox-workbench', 'surface-card', { 'mobile-chat-open': detail }]">
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
					:restore-scroll="listScrollTop"
					@select="selectConversation"
					@scroll-position="rememberListScroll"
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
						<button
							class="mobile-back"
							type="button"
							aria-label="Back to conversations"
							@click="closeMobileConversation"
						>
							<ChevronLeft :size="18" />
						</button>
						<div>
							<strong>{{ detail.display_name }}</strong>
							<span>{{ detail.identity.normalized_value }}</span>
						</div>
						<div class="chat-heading-actions">
							<span>{{ detail.conversation.status }}</span>
							<Button
								text
								rounded
								aria-label="Search this conversation"
								@click="messageSearchOpen = !messageSearchOpen"
							>
								<Search :size="16" />
							</Button>
						</div>
					</header>
					<div v-if="messageSearchOpen" class="message-search-bar">
						<Search :size="15" />
						<InputText
							v-model="messageSearch"
							autofocus
							placeholder="Search messages in this conversation"
						/>
						<Button
							text
							rounded
							aria-label="Close message search"
							@click="closeMessageSearch"
						>
							<X :size="15" />
						</Button>
					</div>
					<div ref="stream" class="message-stream" @scroll.passive="handleStreamScroll">
						<div v-if="messageSearch.trim()" class="search-results">
							<div v-if="messageSearching" class="older-loading">Searching…</div>
							<div v-else-if="!messageSearchRows.length" class="search-empty">
								No matching messages
							</div>
							<MessageBubble
								v-for="message in messageSearchRows"
								:key="message.name"
								:message="message"
								@reply="selectReply"
								@bookmark="toggleBookmark"
								@retry="retryMessage"
							/>
						</div>
						<template v-else>
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
											{{
												topic.summary || 'Open to review grouped messages.'
											}}
										</p>
									</span>
									<em>{{ topic.message_count }} messages</em>
								</summary>
								<div class="topic-messages">
									<MessageBubble
										v-for="message in topic.messageRows"
										:key="message.name"
										:message="message"
										@reply="selectReply"
										@bookmark="toggleBookmark"
										@retry="retryMessage"
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
									@reply="selectReply"
									@bookmark="toggleBookmark"
									@retry="retryMessage"
								/>
							</div>
						</template>
					</div>
					<footer v-if="textReady" class="composer">
						<div v-if="replyTo" class="reply-preview">
							<span
								><strong>Replying to</strong>
								{{ replyTo.body || replyTo.message_type }}</span
							>
							<button
								type="button"
								aria-label="Cancel reply"
								@click="replyTo = null"
							>
								<X :size="14" />
							</button>
						</div>
						<Button text rounded aria-label="Add emoji" @click="addEmoji"
							><Smile :size="18"
						/></Button>
						<Button
							text
							rounded
							aria-label="Send media or rich message"
							@click="richDialog = true"
							><Paperclip :size="18"
						/></Button>
						<Textarea
							v-model="draft"
							auto-resize
							rows="1"
							placeholder="Write a message"
							@keydown.enter.exact.prevent="sendText"
							@focus="showTyping"
							@input="showTyping"
						/>
						<Button :disabled="!draft.trim()" rounded @click="sendText">
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

			<ConversationContext
				v-if="detail"
				:data="detail"
				:can-manage="canManage"
				@status="updateStatus"
			/>
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

		<Dialog
			v-model:visible="richDialog"
			modal
			header="Send a WhatsApp message"
			class="rich-dialog"
		>
			<div class="dialog-form">
				<label
					>Type<Select
						v-model="richForm.type"
						:options="richTypes"
						option-label="label"
						option-value="value"
				/></label>
				<template
					v-if="
						['image', 'video', 'audio', 'document', 'sticker'].includes(richForm.type)
					"
				>
					<label class="media-upload">
						Upload from this device
						<input
							type="file"
							:accept="
								richForm.type === 'sticker'
									? 'image/webp'
									: richForm.type === 'document'
										? undefined
										: `${richForm.type}/*`
							"
							:disabled="uploadingMedia"
							@change="uploadMedia"
						/>
						<small v-if="uploadingMedia">Uploading securely to Meta…</small>
					</label>
					<label>Meta media ID or HTTPS URL<InputText v-model="richForm.media" /></label>
					<label v-if="richForm.type !== 'sticker'"
						>Caption<InputText v-model="richForm.caption"
					/></label>
				</template>
				<template v-else-if="richForm.type === 'reaction'">
					<label>Emoji<InputText v-model="richForm.emoji" /></label>
					<small
						>Select Reply on the target message first. Empty emoji removes the
						reaction.</small
					>
				</template>
				<template v-else-if="richForm.type === 'location'">
					<label>Latitude<InputText v-model="richForm.latitude" /></label>
					<label>Longitude<InputText v-model="richForm.longitude" /></label>
					<label>Name<InputText v-model="richForm.name" /></label>
					<label>Address<InputText v-model="richForm.address" /></label>
				</template>
				<label v-else-if="richForm.type === 'contacts'"
					>Meta contacts JSON<Textarea v-model="richForm.contacts" rows="7"
				/></label>
				<template v-else>
					<label>Published Meta Flow ID<InputText v-model="richForm.flow_id" /></label>
					<label>Flow token<InputText v-model="richForm.flow_token" /></label>
					<label>Starting screen<InputText v-model="richForm.flow_screen" /></label>
					<label>Button label<InputText v-model="richForm.flow_cta" /></label>
					<label>Message<InputText v-model="richForm.flow_body" /></label>
				</template>
			</div>
			<template #footer>
				<Button label="Cancel" text @click="richDialog = false" />
				<Button label="Queue message" :loading="richSending" @click="sendRich" />
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
	.mobile-back {
		display: none;
		padding: 5px;
		border: 0;
		background: transparent;
		color: #45564e;
		cursor: pointer;
	}
	.chat-heading strong,
	.chat-heading span {
		display: block;
	}
	.chat-heading-actions,
	.message-search-bar {
		display: flex;
		align-items: center;
	}
	.chat-heading-actions {
		gap: 6px;
	}
	.message-search-bar {
		gap: 8px;
		padding: 7px 11px;
		border-bottom: 1px solid #e2e9e5;
		color: #718078;
		background: #fff;
	}
	.message-search-bar :deep(input) {
		min-width: 0;
		flex: 1;
		border: 0;
		box-shadow: none;
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
	.topic-messages,
	.search-results {
		display: grid;
		gap: 8px;
	}
	.search-empty {
		margin: auto;
		padding: 20px;
		color: #6d7d75;
		font-size: 11px;
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
	.composer {
		flex-wrap: wrap;
	}
	.reply-preview {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex: 1 0 100%;
		padding: 6px 9px;
		border-left: 3px solid #168a62;
		border-radius: 6px;
		background: #edf8f3;
		font-size: 11px;
	}
	.reply-preview span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.reply-preview button {
		display: inline-flex;
		border: 0;
		background: transparent;
		cursor: pointer;
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
	.media-upload input[type='file'] {
		padding: 8px;
		border: 1px dashed #bdd0c6;
		border-radius: 8px;
		background: #f7faf8;
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
		.chat-panel {
			display: none;
		}
		.mobile-chat-open .list-panel {
			display: none;
		}
		.mobile-chat-open .chat-panel {
			display: flex;
		}
		.mobile-back {
			display: inline-flex;
		}
		.inbox-heading p,
		.inbox-heading .eyebrow {
			display: none;
		}
		.inbox-heading h1 {
			font-size: 20px;
		}
	}
</style>
