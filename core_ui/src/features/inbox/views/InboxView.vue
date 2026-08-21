<script setup>
	import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import AppDialog from '@/components/AppDialog.vue'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Skeleton from 'primevue/skeleton'
	import { useToast } from 'primevue/usetoast'
	import {
		MessageSquarePlus,
		ArrowDown,
		FolderPlus,
		Search,
		ShieldAlert,
		X,
	} from 'lucide-vue-next'

	import ConversationHeader from '@/features/inbox/components/ConversationHeader.vue'
	import CallTimelineEvent from '@/features/inbox/components/CallTimelineEvent.vue'
	import ChannelSelect from '@/features/channels/components/ChannelSelect.vue'
	import ConversationContext from '@/features/inbox/components/ConversationContext.vue'
	import ConversationSummaryPanel from '@/features/inbox/components/ConversationSummaryPanel.vue'
	import ContactMessageEditor from '@/features/inbox/components/ContactMessageEditor.vue'
	import ConversationList from '@/features/inbox/components/ConversationList.vue'
	import { filterAndRankConversations } from '@/features/inbox/utils/conversationSearch'
	import InboxSidebarControls from '@/features/inbox/components/InboxSidebarControls.vue'
	import InboxResizeHandle from '@/features/inbox/components/InboxResizeHandle.vue'
	import MessageActionMenu from '@/features/inbox/components/MessageActionMenu.vue'
	import MessageBubble from '@/features/inbox/components/MessageBubble.vue'
	import MessageComposer from '@/features/inbox/components/MessageComposer.vue'
	import MessageStreamViewport from '@/features/inbox/components/MessageStreamViewport.vue'
	import ContactSelect from '@/features/contacts/components/ContactSelect.vue'
	import TemplateSendDialog from '@/features/templates/components/TemplateSendDialog.vue'
	import TemplateSelect from '@/features/templates/components/TemplateSelect.vue'
	import { call, errorMessage, uploadFile } from '@/services/frappe'
	import { subscribe, subscribeConnection } from '@/services/realtime'
	import { useSessionStore } from '@/stores/session'
	import { formatDateTime } from '@/utils/datetime'
	import { focusDialogControl } from '@/utils/focus'

	const route = useRoute()
	const router = useRouter()
	const toast = useToast()
	const session = useSessionStore()
	const canManage = computed(() => Boolean(session.boot?.can_manage))
	const loading = ref(true)
	const listError = ref('')
	const detailLoading = ref(false)
	const detailError = ref('')
	const loadingOlder = ref(false)
	const richSending = ref(false)
	const search = ref('')
	const listMode = ref('all')
	const team = ref(String(route.query.team || ''))
	const folder = ref(String(route.query.folder || ''))
	const folders = ref([])
	const folderDialog = ref(false)
	const folderName = ref('')
	const folderColor = ref('#22c55e')
	const savingFolder = ref(false)
	const rows = ref([])
	const conversationViewers = ref([])
	const conversationPage = ref({ has_more: false })
	const loadingMoreRows = ref(false)
	const listScrollTop = ref(Number(sessionStorage.getItem('whatsapp:inbox-scroll') || 0))
	const listPaneWidth = ref(Number(localStorage.getItem('whatsapp:inbox-pane-width') || 360))
	const detail = ref(null)
	const detailTeams = computed(() => {
		const values = [
			detail.value?.assigned_team_details,
			...(detail.value?.contact_teams || []),
		]
		return [...new Map(values.filter(Boolean).map((item) => [item.name, item])).values()]
	})
	const contextOpen = ref(false)
	const viewMode = ref(localStorage.getItem('whatsapp:conversation-view') || 'chat')
	const summaryRefreshing = ref(false)
	const messagePage = ref({ has_more: false, has_more_newer: false })
	const loadingNewer = ref(false)
	const messageSearchOpen = ref(false)
	const messageSearchInput = ref(null)
	const messageSearch = ref('')
	const messageSearchRows = ref([])
	const messageSearching = ref(false)
	const draft = ref('')
	const replyTo = ref(null)
	const messageMenu = ref(null)
	const messageMenuPosition = ref({ x: 0, y: 0 })
	const messageInfo = ref(null)
	const messageInfoOpen = ref(false)
	const quickReactions = ['👍', '❤️', '😂', '😮', '😢', '🙏']
	const richDialog = ref(false)
	const richDialogRef = ref(null)
	const uploadingMedia = ref(false)
	const blankContact = () => ({
		formatted_name: '',
		first_name: '',
		last_name: '',
		phone: '',
		phone_type: 'CELL',
		email: '',
		email_type: 'WORK',
		company: '',
		title: '',
	})
	const richForm = ref({
		type: 'image',
		media: '',
		local_file_url: '',
		caption: '',
		emoji: '👍',
		latitude: '',
		longitude: '',
		name: '',
		address: '',
		contacts: [blankContact()],
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
	let typingActive = false
	let typingDelayTimer = null
	let typingIdleTimer = null
	let typingRefreshTimer = null
	let messageSearchTimer = null
	let conversationSearchTimer = null
	let presenceHeartbeatTimer = null
	let presenceConversation = ''
	const presenceClientId = browserPresenceId()
	const stream = ref(null)
	const hasUnseenMessages = ref(false)
	const atMessageBottom = ref(true)
	const jumpingToLatest = ref(false)
	const messageScrollPositions = readMessageScrollPositions()
	const newDialog = ref(false)
	const newDialogRef = ref(null)
	const starting = ref(false)
	const catalog = ref({ templates: [] })
	const templateDialog = ref(false)
	const selectedTemplate = ref('')
	const settings = ref({ channels: [] })
	const newChatContacts = ref([])
	const newConversationModes = [
		{ label: 'Open chat', value: 'message' },
		{ label: 'Start with template', value: 'template' },
	]
	const newChat = ref({
		channel: '',
		identity: '',
		phone_number: '',
		display_name: '',
		mode: 'message',
		template: '',
	})
	const openingTemplates = computed(() =>
		catalog.value.templates.filter(
			(template) =>
				template.channel === newChat.value.channel &&
				template.enabled &&
				template.approval_status === 'APPROVED',
		),
	)
	const unsubscribers = []
	let listRequest = 0
	let detailRequest = 0
	let olderRequest = 0
	let messageSearchRequest = 0
	let batchRefreshTimer = null
	let pendingBatchEvents = []
	let readBatchTimer = null
	let readScanFrame = null
	const pendingReadMessages = new Map()
	const locallyReadMessages = new Set()
	const optimisticReadCursors = new Map()
	const clearedConversationBadges = new Set()
	let realtimeConnectedOnce = false
	let restoringMessageScroll = false

	function browserPresenceId() {
		const storageKey = 'whatsapp:presence-client'
		try {
			const existing = sessionStorage.getItem(storageKey)
			if (existing) return existing
			const created =
				globalThis.crypto?.randomUUID?.().replaceAll('-', '') ||
				`${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
			sessionStorage.setItem(storageKey, created)
			return created
		} catch {
			return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`
		}
	}

	function readMessageScrollPositions() {
		try {
			const stored = JSON.parse(sessionStorage.getItem('whatsapp:message-scrolls') || '{}')
			return stored && typeof stored === 'object' ? stored : {}
		} catch {
			return {}
		}
	}

	function isNearMessageBottom(threshold = 96) {
		if (!stream.value) return true
		const distance =
			stream.value.scrollHeight - stream.value.clientHeight - stream.value.scrollTop
		return distance <= threshold
	}

	function updateMessageBottomState() {
		atMessageBottom.value = !messagePage.value.has_more_newer && isNearMessageBottom()
	}

	function rememberMessageScroll(conversation = selectedName.value) {
		if (!conversation || !stream.value || restoringMessageScroll) return
		const distanceFromBottom = Math.max(
			0,
			stream.value.scrollHeight - stream.value.clientHeight - stream.value.scrollTop,
		)
		messageScrollPositions[conversation] = {
			distanceFromBottom,
			atBottom: distanceFromBottom <= 96,
		}
		try {
			sessionStorage.setItem(
				'whatsapp:message-scrolls',
				JSON.stringify(messageScrollPositions),
			)
		} catch {
			// A full sessionStorage must not interrupt inbox navigation.
		}
	}

	const selectedName = computed(() => route.params.conversation || '')
	const listPaneMaxWidth = computed(() => Math.max(320, Math.min(620, window.innerWidth * 0.48)))
	const workbenchStyle = computed(() => ({
		'--conversation-pane-width': `${Math.min(listPaneWidth.value, listPaneMaxWidth.value)}px`,
	}))

	function resizeListPane(width) {
		listPaneWidth.value = Math.max(270, Math.min(listPaneMaxWidth.value, Number(width) || 360))
		localStorage.setItem('whatsapp:inbox-pane-width', String(listPaneWidth.value))
	}

	const filteredRows = computed(() => {
		return filterAndRankConversations(rows.value, search.value).filter(
			(row) => listMode.value !== 'unread' || Number(row.unread_count || 0) > 0,
		)
	})
	const messageMap = computed(
		() => new Map((detail.value?.messages || []).map((message) => [message.name, message])),
	)
	const providerMessageMap = computed(
		() =>
			new Map(
				(detail.value?.messages || [])
					.filter((message) => message.provider_message_id)
					.map((message) => [message.provider_message_id, message]),
			),
	)
	const readersByMessage = computed(() => {
		const result = new Map()
		// Exact per-message reads stay on each message for unread accounting and
		// audit. The chat presentation is a read cursor: show each operator once,
		// under only the furthest message they have read. Operators at the same
		// cursor naturally share one marker row.
		for (const reader of detail.value?.readers || []) {
			if (!reader.last_read_message || !messageMap.value.has(reader.last_read_message))
				continue
			const readers = result.get(reader.last_read_message) || []
			readers.push(reader)
			result.set(reader.last_read_message, readers)
		}
		return result
	})
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
	function timelineTimestamp(value) {
		const raw =
			value?.timeline_at ||
			value?.provider_timestamp ||
			value?.started_at ||
			value?.ended_at ||
			value?.creation ||
			value?.modified
		const timestamp = new Date(raw || 0).getTime()
		return Number.isFinite(timestamp) ? timestamp : 0
	}
	const visibleCalls = computed(() => {
		const calls = detail.value?.calls || []
		const messages = detail.value?.messages || []
		if (!messages.length) return calls
		const timestamps = messages.map(timelineTimestamp).filter(Boolean)
		if (!timestamps.length) return calls
		const oldest = Math.min(...timestamps)
		const newest = Math.max(...timestamps)
		return calls.filter((callRow) => {
			const at = timelineTimestamp(callRow)
			return (
				(!messagePage.value.has_more || at >= oldest) &&
				(!messagePage.value.has_more_newer || at <= newest)
			)
		})
	})
	const timelineItems = computed(() =>
		[
			...ungrouped.value.map((message) => ({
				kind: 'message',
				key: `message:${message.name}`,
				value: message,
			})),
			...visibleCalls.value.map((callRow) => ({
				kind: 'call',
				key: `call:${callRow.name || callRow.call_id}`,
				value: callRow,
			})),
		].sort(
			(left, right) =>
				timelineTimestamp(left.value) - timelineTimestamp(right.value) ||
				left.key.localeCompare(right.key),
		),
	)
	const textReady = computed(() => Boolean(detail.value?.outbound?.text_ready))

	async function loadRows({ silent = false } = {}) {
		const request = ++listRequest
		const query = search.value.trim()
		if (!silent) loading.value = true
		listError.value = ''
		try {
			const loaded = await call('frappe_whatsapp_core.inbox.conversation_page', {
				limit: query ? 100 : 20,
				team: team.value || null,
				folder: folder.value || null,
				search: query || null,
			})
			if (request !== listRequest) return
			const currentUnread = new Map(
				rows.value.map((row) => [row.name, Number(row.unread_count || 0)]),
			)
			rows.value = (loaded.rows || []).map((row) =>
				clearedConversationBadges.has(row.name)
					? { ...row, unread_count: currentUnread.get(row.name) || 0 }
					: row,
			)
			conversationPage.value = loaded
		} catch (error) {
			if (request === listRequest)
				listError.value = errorMessage(error, 'Unable to load conversations.')
		} finally {
			if (request === listRequest && !silent) loading.value = false
		}
	}

	async function loadMoreRows() {
		if (!conversationPage.value.has_more || loadingMoreRows.value) return
		loadingMoreRows.value = true
		const request = listRequest
		try {
			const loaded = await call('frappe_whatsapp_core.inbox.conversation_page', {
				limit: search.value.trim() ? 100 : 20,
				before: conversationPage.value.next_before,
				before_name: conversationPage.value.next_before_name,
				team: team.value || null,
				folder: folder.value || null,
				search: search.value.trim() || null,
			})
			if (request !== listRequest) return
			const known = new Set(rows.value.map((row) => row.name))
			rows.value.push(...(loaded.rows || []).filter((row) => !known.has(row.name)))
			conversationPage.value = loaded
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Could not load more conversations',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			loadingMoreRows.value = false
		}
	}

	async function loadDetail(name, { silent = false } = {}) {
		const request = ++detailRequest
		const preservedPosition =
			silent && stream.value
				? {
						distanceFromBottom: Math.max(
							0,
							stream.value.scrollHeight -
								stream.value.clientHeight -
								stream.value.scrollTop,
						),
						atBottom: isNearMessageBottom(),
					}
				: null
		const hadUnread =
			Number(rows.value.find((item) => item.name === name)?.unread_count || 0) > 0
		let resumeMessage = null
		olderRequest += 1
		messageSearchRequest += 1
		if (!name) {
			detail.value = null
			detailLoading.value = false
			detailError.value = ''
			loadingOlder.value = false
			atMessageBottom.value = true
			return
		}
		if (!silent) {
			detailLoading.value = true
			detail.value = null
		}
		detailError.value = ''
		try {
			const loaded = await call('frappe_whatsapp_core.inbox.conversation', { name })
			if (request !== detailRequest) return
			detail.value = loaded
			resumeMessage = loaded.resume_message || null
			messagePage.value = detail.value.message_page || {
				has_more: false,
				has_more_newer: false,
			}
		} catch (error) {
			if (request === detailRequest && !silent)
				detailError.value = errorMessage(error, 'Unable to load this conversation.')
		} finally {
			if (request === detailRequest) {
				if (!silent) detailLoading.value = false
				await restoreMessageScroll(name, {
					forceBottom: !resumeMessage,
					fallback: preservedPosition,
					resumeMessage,
					preferResume: hadUnread,
				})
				queueVisibleMessages()
			}
		}
	}

	function visiblePresenceViewers(viewers) {
		const currentUser = session.user?.name
		return (viewers || []).filter((viewer) => viewer.user && viewer.user !== currentUser)
	}

	function applyConversationPresence(event) {
		if (event?.conversation !== selectedName.value || document.visibilityState === 'hidden')
			return
		conversationViewers.value = visiblePresenceViewers(event.viewers)
	}

	async function touchConversationPresence(conversation, active) {
		if (!conversation) return
		try {
			const result = await call(
				'frappe_whatsapp_core.conversation_presence.update_conversation_presence',
				{
					conversation,
					client_id: presenceClientId,
					active: active ? 1 : 0,
				},
			)
			if (active && conversation === selectedName.value)
				conversationViewers.value = visiblePresenceViewers(result?.viewers)
		} catch {
			// Presence is advisory. Messaging must remain usable during a cache outage.
		}
	}

	function leaveConversationPresence(conversation = presenceConversation) {
		if (!conversation) return
		if (presenceConversation === conversation) presenceConversation = ''
		window.clearInterval(presenceHeartbeatTimer)
		presenceHeartbeatTimer = null
		conversationViewers.value = []
		void touchConversationPresence(conversation, false)
	}

	function enterConversationPresence(conversation) {
		if (!conversation || document.visibilityState === 'hidden') return
		if (presenceConversation && presenceConversation !== conversation)
			leaveConversationPresence(presenceConversation)
		presenceConversation = conversation
		void touchConversationPresence(conversation, true)
		window.clearInterval(presenceHeartbeatTimer)
		presenceHeartbeatTimer = window.setInterval(() => {
			if (presenceConversation && document.visibilityState !== 'hidden')
				void touchConversationPresence(presenceConversation, true)
		}, 45_000)
	}

	function handlePresenceVisibilityChange() {
		if (document.visibilityState === 'hidden') leaveConversationPresence()
		else enterConversationPresence(selectedName.value)
	}

	async function refreshDirectoryPresentations() {
		await loadRows({ silent: true })
		if (selectedName.value) await loadDetail(selectedName.value, { silent: true })
	}

	async function restoreMessageScroll(
		name,
		{ forceBottom = false, fallback = null, resumeMessage = null, preferResume = false } = {},
	) {
		await nextTick()
		if (!stream.value || name !== selectedName.value) return
		const saved = fallback || messageScrollPositions[name]
		if (resumeMessage && (preferResume || !saved)) {
			const target = [...stream.value.querySelectorAll('[data-message-name]')].find(
				(element) => element.dataset.messageName === resumeMessage,
			)
			if (target) {
				target.closest('details')?.setAttribute('open', '')
				await nextTick()
				await waitForMessageLayout()
				const viewportBounds = stream.value.getBoundingClientRect()
				const targetBounds = target.getBoundingClientRect()
				stream.value.scrollTop = Math.max(
					0,
					stream.value.scrollTop + targetBounds.top - viewportBounds.top - 8,
				)
				updateMessageBottomState()
				return
			}
		}
		if (forceBottom || !saved || saved.atBottom) {
			await scrollToBottom()
			return
		}
		restoringMessageScroll = true
		try {
			const desiredDistance = Math.max(0, Number(saved.distanceFromBottom || 0))
			let pages = 0
			while (
				messagePage.value.has_more &&
				stream.value.scrollHeight - stream.value.clientHeight < desiredDistance &&
				pages < 20
			) {
				await loadOlderMessages()
				pages += 1
				await nextTick()
			}
			stream.value.scrollTop = Math.max(
				0,
				stream.value.scrollHeight - stream.value.clientHeight - desiredDistance,
			)
			updateMessageBottomState()
		} finally {
			restoringMessageScroll = false
		}
	}

	async function waitForMessageLayout() {
		const pendingMedia = [...stream.value.querySelectorAll('img, video')].filter(
			(element) =>
				(element.tagName === 'IMG' && !element.complete) ||
				(element.tagName === 'VIDEO' && element.readyState < 1),
		)
		if (!pendingMedia.length) return
		await Promise.race([
			Promise.all(
				pendingMedia.map(
					(element) =>
						new Promise((resolve) => {
							element.addEventListener('load', resolve, { once: true })
							element.addEventListener('error', resolve, { once: true })
							element.addEventListener('loadedmetadata', resolve, { once: true })
						}),
				),
			),
			new Promise((resolve) => window.setTimeout(resolve, 1200)),
		])
		await nextTick()
	}

	async function loadOlderMessages() {
		if (!detail.value || !messagePage.value.has_more || loadingOlder.value || !stream.value)
			return
		const request = ++olderRequest
		const conversation = selectedName.value
		const currentDetail = detail.value
		loadingOlder.value = true
		const previousHeight = stream.value.scrollHeight
		try {
			const page = await call('frappe_whatsapp_core.workspace_api.list_messages', {
				conversation,
				before: messagePage.value.next_before,
				before_creation: messagePage.value.next_before_creation,
				before_name: messagePage.value.next_before_name,
				limit: 20,
			})
			if (
				request !== olderRequest ||
				conversation !== selectedName.value ||
				detail.value !== currentDetail
			)
				return
			const known = new Set(currentDetail.messages.map((message) => message.name))
			const older = [...page.rows].reverse().filter((message) => !known.has(message.name))
			currentDetail.messages.unshift(...older)
			messagePage.value = {
				...messagePage.value,
				has_more: page.has_more,
				next_before: page.next_before,
				next_before_creation: page.next_before_creation,
				next_before_name: page.next_before_name,
			}
			await nextTick()
			stream.value.scrollTop = stream.value.scrollHeight - previousHeight
			updateMessageBottomState()
		} catch (error) {
			if (request !== olderRequest || conversation !== selectedName.value) return
			toast.add({
				severity: 'error',
				summary: 'Could not load older messages',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			if (request === olderRequest) loadingOlder.value = false
		}
	}

	async function loadNewerMessages() {
		if (
			!detail.value ||
			!messagePage.value.has_more_newer ||
			loadingNewer.value ||
			!stream.value
		)
			return
		const conversation = selectedName.value
		const currentDetail = detail.value
		loadingNewer.value = true
		try {
			const page = await call('frappe_whatsapp_core.workspace_api.list_messages', {
				conversation,
				after: messagePage.value.next_after,
				after_creation: messagePage.value.next_after_creation,
				after_name: messagePage.value.next_after_name,
				limit: 20,
			})
			if (conversation !== selectedName.value || detail.value !== currentDetail) return
			const known = new Set(currentDetail.messages.map((message) => message.name))
			currentDetail.messages.push(...page.rows.filter((message) => !known.has(message.name)))
			messagePage.value = {
				...messagePage.value,
				has_more_newer: page.has_more,
				next_after: page.next_after,
				next_after_creation: page.next_after_creation,
				next_after_name: page.next_after_name,
			}
			await nextTick()
			updateMessageBottomState()
			queueVisibleMessages()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Could not load newer messages',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			loadingNewer.value = false
		}
	}

	function cursorPosition(value) {
		return [
			String(value?.provider_timestamp || value?.last_read_at || ''),
			String(value?.creation || value?.last_read_creation || ''),
			String(value?.name || value?.last_read_message || ''),
		]
	}

	function compareCursorPosition(left, right) {
		const leftPosition = cursorPosition(left)
		const rightPosition = cursorPosition(right)
		if (leftPosition[0] !== rightPosition[0])
			return leftPosition[0].localeCompare(rightPosition[0])
		if (leftPosition[1] !== rightPosition[1])
			return leftPosition[1].localeCompare(rightPosition[1])
		return leftPosition[2].localeCompare(rightPosition[2])
	}

	function isAlreadyRead(message) {
		return (message.read_by || []).some((reader) => reader.user === session.user?.name)
	}

	function isMessageVisible(element, viewport) {
		const bounds = element.getBoundingClientRect()
		const visibleHeight = Math.max(
			0,
			Math.min(bounds.bottom, viewport.bottom) - Math.max(bounds.top, viewport.top),
		)
		const requiredHeight = Math.min(48, Math.max(1, bounds.height * 0.5))
		return visibleHeight >= requiredHeight
	}

	function queueVisibleMessages() {
		window.cancelAnimationFrame(readScanFrame)
		readScanFrame = window.requestAnimationFrame(() => {
			const conversation = selectedName.value
			if (!conversation || !stream.value || !detail.value) return
			if (document.visibilityState !== 'visible' || !document.hasFocus()) return
			const viewport = stream.value.getBoundingClientRect()
			const messagesByName = new Map(
				detail.value.messages.map((message) => [message.name, message]),
			)
			const visibleNames = new Set()
			for (const element of stream.value.querySelectorAll('[data-message-name]')) {
				const name = element.dataset.messageName
				const message = messagesByName.get(name)
				if (
					!message ||
					message.optimistic ||
					name.startsWith('optimistic:') ||
					locallyReadMessages.has(name) ||
					isAlreadyRead(message)
				)
					continue
				if (!isMessageVisible(element, viewport)) continue
				visibleNames.add(name)
			}
			window.clearTimeout(readBatchTimer)
			if (!visibleNames.size) {
				pendingReadMessages.delete(conversation)
				return
			}
			// Replace rather than accumulate. During continuous or smooth scrolling,
			// only the messages in the final settled viewport survive the 400 ms dwell.
			pendingReadMessages.set(conversation, visibleNames)
			readBatchTimer = window.setTimeout(flushReadBatch, 400)
		})
	}

	function discardPendingReadMessages(conversation = selectedName.value) {
		window.clearTimeout(readBatchTimer)
		readBatchTimer = null
		window.cancelAnimationFrame(readScanFrame)
		if (conversation) pendingReadMessages.delete(conversation)
	}

	function handleReadVisibilityChange() {
		if (document.visibilityState === 'visible' && document.hasFocus()) {
			queueVisibleMessages()
			return
		}
		discardPendingReadMessages()
	}

	async function flushReadBatch() {
		window.clearTimeout(readBatchTimer)
		readBatchTimer = null
		const entry = [...pendingReadMessages.entries()].find(([, names]) => names.size)
		if (!entry) return
		const [conversation, pending] = entry
		const names = [...pending].slice(0, 100)
		for (const name of names) locallyReadMessages.add(name)
		for (const name of names) pending.delete(name)
		if (!pending.size) pendingReadMessages.delete(conversation)
		const visibleMessages = (detail.value?.messages || []).filter((message) =>
			names.includes(message.name),
		)
		const newlyReadInbound = visibleMessages.filter(
			(message) => message.direction === 'Inbound',
		).length
		const row = rows.value.find((item) => item.name === conversation)
		if (row) row.unread_count = Math.max(0, Number(row.unread_count || 0) - newlyReadInbound)
		const latest = visibleMessages.reduce(
			(current, message) =>
				!current || compareCursorPosition(message, current) > 0 ? message : current,
			null,
		)
		const previousRead =
			conversation === selectedName.value ? detail.value?.current_user_read || null : null
		if (conversation === selectedName.value && latest) {
			const optimisticRead = {
				conversation,
				user: session.user?.name,
				last_read_message: latest.name,
				last_read_at: latest.provider_timestamp,
				last_read_creation: latest.creation,
				messages: names,
			}
			optimisticReadCursors.set(conversation, optimisticRead)
			updateConversationReader(optimisticRead)
		}
		try {
			const savedRead = await call(
				'frappe_whatsapp_core.conversation_reads.mark_messages_read',
				{ conversation, messages: names },
			)
			if (conversation === selectedName.value && savedRead?.last_read_message)
				updateConversationReader(savedRead)
			const optimistic = optimisticReadCursors.get(conversation)
			if (latest && optimistic?.last_read_message === latest.name)
				optimisticReadCursors.delete(conversation)
		} catch (error) {
			for (const name of names) locallyReadMessages.delete(name)
			const retryPending = pendingReadMessages.get(conversation) || new Set()
			for (const name of names) retryPending.add(name)
			pendingReadMessages.set(conversation, retryPending)
			if (row) row.unread_count = Number(row.unread_count || 0) + newlyReadInbound
			const optimistic = optimisticReadCursors.get(conversation)
			if (conversation === selectedName.value && detail.value) {
				const failedNames = new Set(names)
				for (const message of detail.value.messages || []) {
					if (!failedNames.has(message.name)) continue
					message.read_by = (message.read_by || []).filter(
						(reader) => reader.user !== session.user?.name,
					)
				}
			}
			if (latest && optimistic?.last_read_message === latest.name) {
				optimisticReadCursors.delete(conversation)
				if (conversation === selectedName.value && detail.value) {
					detail.value.current_user_read = previousRead
					const readers = (detail.value.readers || []).filter(
						(reader) => reader.user !== session.user?.name,
					)
					if (previousRead) readers.unshift(previousRead)
					detail.value.readers = readers
				}
			}
			toast.add({
				severity: 'error',
				summary: 'Read position not saved',
				detail: errorMessage(error),
				life: 3500,
			})
			// Keep the failed batch available for the next visibility/scroll event,
			// but do not retry it in a 250 ms loop. A temporary permission or network
			// failure otherwise creates an unbounded stream of identical popups.
			return
		}
		if ([...pendingReadMessages.values()].some((items) => items.size))
			readBatchTimer = window.setTimeout(flushReadBatch, 250)
	}

	function handleStreamScroll() {
		if (isNearMessageBottom()) hasUnseenMessages.value = false
		updateMessageBottomState()
		rememberMessageScroll()
		queueVisibleMessages()
		if (stream.value?.scrollTop <= 64) loadOlderMessages()
		if (isNearMessageBottom(160)) loadNewerMessages()
	}

	function selectConversation(name) {
		if (name === selectedName.value) return
		clearConversationBadge(name)
		rememberMessageScroll()
		router.push({
			name: 'inbox',
			params: { conversation: name },
			state: { fromInbox: true },
		})
	}

	function clearConversationBadge(name) {
		if (!name) return
		const row = rows.value.find((item) => item.name === name)
		if (row) row.unread_count = 0
		clearedConversationBadges.add(name)
	}

	function closeMobileConversation() {
		rememberMessageScroll()
		if (window.history.state?.fromInbox) router.back()
		else router.replace({ name: 'inbox' })
	}

	function rememberListScroll(value) {
		listScrollTop.value = value
		sessionStorage.setItem('whatsapp:inbox-scroll', String(value))
	}

	async function runMessageSearch() {
		const request = ++messageSearchRequest
		const query = messageSearch.value.trim()
		const conversation = selectedName.value
		if (!query || !conversation) {
			messageSearchRows.value = []
			messageSearching.value = false
			return
		}
		messageSearching.value = true
		try {
			const result = await call('frappe_whatsapp_core.workspace_api.list_messages', {
				conversation,
				search: query,
				limit: 100,
			})
			if (request !== messageSearchRequest || conversation !== selectedName.value) return
			messageSearchRows.value = [...result.rows].reverse()
		} catch (error) {
			if (request !== messageSearchRequest) return
			messageSearchRows.value = []
			toast.add({
				severity: 'error',
				summary: 'Search failed',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			if (request === messageSearchRequest) messageSearching.value = false
		}
	}

	function closeMessageSearch() {
		messageSearchRequest += 1
		messageSearchOpen.value = false
		messageSearch.value = ''
		messageSearchRows.value = []
	}

	async function toggleMessageSearch() {
		if (messageSearchOpen.value) {
			closeMessageSearch()
			return
		}
		messageSearchOpen.value = true
		await nextTick()
		messageSearchInput.value?.$el?.focus()
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
			owner: session.user?.name || '',
			sender_name: session.user?.full_name || session.user?.name || 'You',
			optimistic: true,
		}
	}

	function reconcileMessage(message, conversation = selectedName.value) {
		if (!detail.value || !message || conversation !== selectedName.value) return
		if (message.message_type === 'reaction') {
			applyReactionMessage(message)
			return
		}
		const index = detail.value.messages.findIndex(
			(item) =>
				item.name === message.name ||
				(item.provider_message_id &&
					item.provider_message_id === message.provider_message_id),
		)
		if (index >= 0) detail.value.messages.splice(index, 1, message)
		else detail.value.messages.push(message)
	}

	function reactionPayload(message) {
		let content = message?.content || {}
		if (typeof content === 'string') {
			try {
				content = JSON.parse(content)
			} catch {
				content = {}
			}
		}
		return content.reaction || content.payload?.reaction || content.payload || {}
	}

	function applyReactionMessage(message) {
		if (!detail.value || message?.conversation !== selectedName.value) return
		const reaction = reactionPayload(message)
		const target = detail.value.messages.find(
			(row) => row.provider_message_id === reaction.message_id,
		)
		if (!target) return
		const actorKey = `${message.direction}:${message.owner || 'remote'}`
		const existing = (target.reactions || []).filter((item) => item.actor_key !== actorKey)
		if (reaction.emoji) {
			existing.push({
				message: message.name,
				emoji: reaction.emoji,
				direction: message.direction,
				actor_key: actorKey,
				owner: message.owner || '',
				actor:
					message.direction === 'Outbound'
						? message.sender_name || message.owner || 'You'
						: 'Contact',
				provider_timestamp: message.provider_timestamp,
			})
		}
		target.reactions = existing
	}

	async function queueText(body, contextMessageId = '') {
		const conversation = selectedName.value
		const optimistic = optimisticText(body, contextMessageId)
		reconcileMessage(optimistic, conversation)
		scrollToBottom()
		try {
			const message = await call('frappe_whatsapp_core.outbound.queue_text', {
				conversation_name: conversation,
				body,
				context_message_id: contextMessageId,
				client_message_id: optimistic.client_message_id,
			})
			reconcileMessage(message, conversation)
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
		stopTypingSession()
		await queueText(body, contextMessageId)
	}

	async function retryMessage(message) {
		if (message.message_type !== 'text') return
		await queueText(message.body || '')
	}

	function selectReply(message) {
		replyTo.value = message
	}

	async function openQuotedMessage(message) {
		if (!message?.name || !stream.value) return
		if (messageSearchOpen.value) closeMessageSearch()
		let target = null
		for (let page = 0; page < 20; page += 1) {
			await nextTick()
			target = [...stream.value.querySelectorAll('[data-message-name]')].find(
				(element) => element.dataset.messageName === message.name,
			)
			if (target || !messagePage.value.has_more) break
			await loadOlderMessages()
		}
		if (!target) return
		target.closest('details')?.setAttribute('open', '')
		target.scrollIntoView({ block: 'center', behavior: 'smooth' })
		target.classList.remove('quote-highlight')
		void target.offsetWidth
		target.classList.add('quote-highlight')
		window.setTimeout(() => target?.classList.remove('quote-highlight'), 1300)
	}

	function openMessageMenu({ message, x, y }) {
		const menuWidth = 250
		const menuHeight = 330
		messageMenuPosition.value = {
			x: Math.max(10, Math.min(Number(x) || 10, window.innerWidth - menuWidth - 10)),
			y: Math.max(10, Math.min(Number(y) || 10, window.innerHeight - menuHeight - 10)),
		}
		messageMenu.value = message
	}

	function closeMessageMenu() {
		messageMenu.value = null
	}

	function replyFromMenu() {
		if (!messageMenu.value) return
		selectReply(messageMenu.value)
		closeMessageMenu()
	}

	function showMessageInfo() {
		if (!messageMenu.value) return
		messageInfo.value = messageMenu.value
		messageInfoOpen.value = true
		closeMessageMenu()
	}

	function isMediaMessage(message) {
		return ['audio', 'document', 'image', 'sticker', 'video'].includes(
			String(message?.message_type || '').toLowerCase(),
		)
	}

	function downloadMedia(message = messageMenu.value) {
		if (!message?.media_url) return
		const link = document.createElement('a')
		const url = new URL(message.media_url, window.location.origin)
		if (url.origin === window.location.origin) url.searchParams.set('download', '1')
		link.href = url.toString()
		link.download = ''
		link.rel = 'noreferrer'
		document.body.appendChild(link)
		link.click()
		link.remove()
		closeMessageMenu()
	}

	async function reactToMessage(emoji) {
		const target = messageMenu.value
		if (!target?.provider_message_id || target.provider_message_id.startsWith('local:')) {
			toast.add({
				severity: 'warn',
				summary: 'Reaction unavailable',
				detail: 'Wait until this message has been accepted by WhatsApp.',
				life: 3500,
			})
			return
		}
		closeMessageMenu()
		try {
			const message = await call('frappe_whatsapp_core.outbound.queue_rich', {
				conversation_name: selectedName.value,
				message_type: 'reaction',
				payload: { message_id: target.provider_message_id, emoji },
			})
			applyReactionMessage(message)
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Reaction not queued',
				detail: errorMessage(error),
				life: 5000,
			})
		}
	}

	function formatInfoTime(value) {
		return formatDateTime(value)
	}

	function handleGlobalKeydown(event) {
		if (event.key === 'Escape') closeMessageMenu()
	}

	async function publishTypingIndicator(conversation) {
		if (!typingActive || conversation !== selectedName.value || !draft.value.trim()) return
		try {
			await call('frappe_whatsapp_core.conversation_reads.show_typing', {
				conversation,
			})
		} catch {
			// Typing state is transient and must never interrupt composing.
		}
	}

	async function startTypingSession() {
		const conversation = selectedName.value
		if (!conversation || typingActive || !draft.value.trim()) return
		typingActive = true
		await publishTypingIndicator(conversation)
		window.clearInterval(typingRefreshTimer)
		typingRefreshTimer = window.setInterval(() => publishTypingIndicator(conversation), 10_000)
	}

	function noteTyping() {
		window.clearTimeout(typingDelayTimer)
		window.clearTimeout(typingIdleTimer)
		if (!draft.value.trim()) {
			stopTypingSession()
			return
		}
		// Do not light up the customer's typing indicator merely because the
		// composer received focus. Start only after actual, settled input.
		typingDelayTimer = window.setTimeout(startTypingSession, 350)
		typingIdleTimer = window.setTimeout(stopTypingSession, 1800)
	}

	function stopTypingSession() {
		window.clearTimeout(typingDelayTimer)
		window.clearTimeout(typingIdleTimer)
		window.clearInterval(typingRefreshTimer)
		typingDelayTimer = null
		typingIdleTimer = null
		typingRefreshTimer = null
		typingActive = false
	}

	function addEmoji() {
		draft.value += '😊'
		noteTyping()
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
			const contacts = richForm.value.contacts.map((contact, index) => {
				const formattedName = contact.formatted_name.trim()
				const phone = contact.phone.trim()
				if (!formattedName || !phone) {
					throw new Error(
						`Contact ${index + 1} requires a display name and phone number.`,
					)
				}
				const name = { formatted_name: formattedName }
				if (contact.first_name.trim()) name.first_name = contact.first_name.trim()
				if (contact.last_name.trim()) name.last_name = contact.last_name.trim()
				const value = {
					name,
					phones: [{ phone, type: contact.phone_type || 'CELL' }],
				}
				if (contact.email.trim()) {
					value.emails = [
						{ email: contact.email.trim(), type: contact.email_type || 'WORK' },
					]
				}
				if (contact.company.trim() || contact.title.trim()) {
					value.org = {
						company: contact.company.trim(),
						title: contact.title.trim(),
					}
				}
				return value
			})
			return { contacts, context_message_id }
		}
		const flowActionPayload = { screen: richForm.value.flow_screen }
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
					flow_action_payload: flowActionPayload,
				},
			},
			context_message_id,
		}
	}

	async function uploadMedia(event) {
		const file = event.target.files?.[0]
		if (!file) return
		const conversation = selectedName.value
		uploadingMedia.value = true
		try {
			const stored = await uploadFile(file, true)
			const uploaded = await call('frappe_whatsapp_core.outbound.upload_media', {
				conversation_name: conversation,
				file_url: stored.file_url,
				media_type: richForm.value.type,
			})
			richForm.value.media = uploaded.media_id
			richForm.value.local_file_url = uploaded.file_url
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
		const conversation = selectedName.value
		const optimistic = optimisticText(
			richForm.value.caption.trim() || richForm.value.flow_body.trim() || `[${type}]`,
		)
		optimistic.message_type = type
		optimistic.content = { payload }
		richSending.value = true
		reconcileMessage(optimistic, conversation)
		scrollToBottom()
		richDialog.value = false
		replyTo.value = null
		stopTypingSession()
		try {
			const message = await call('frappe_whatsapp_core.outbound.queue_rich', {
				conversation_name: conversation,
				message_type: type,
				payload,
				client_message_id: optimistic.client_message_id,
				local_file_url: richForm.value.local_file_url || null,
			})
			reconcileMessage(message, conversation)
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
		} finally {
			richSending.value = false
		}
	}

	async function sendTemplate(payload) {
		if (!payload?.template) return
		const conversation = selectedName.value
		richSending.value = true
		try {
			const message = await call('frappe_whatsapp_core.outbound.queue_template', {
				conversation_name: conversation,
				template: payload.template,
				language_code: payload.language_code,
				components: payload.components,
				local_file_url: payload.local_file_url || null,
			})
			appendMessage({ conversation, message })
			templateDialog.value = false
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Template not sent',
				detail: errorMessage(error),
				life: 5000,
			})
		} finally {
			richSending.value = false
		}
	}

	async function startConversation() {
		starting.value = true
		try {
			const openingTemplate = newChat.value.mode === 'template' ? newChat.value.template : ''
			const started = await call('frappe_whatsapp_core.outbound.start_conversation', {
				channel: newChat.value.channel,
				identity: newChat.value.identity || null,
				phone_number: newChat.value.phone_number,
				display_name: newChat.value.display_name,
			})
			newDialog.value = false
			newChat.value = {
				channel: '',
				identity: '',
				phone_number: '',
				display_name: '',
				mode: 'message',
				template: '',
			}
			await loadRows()
			selectConversation(started.conversation)
			if (openingTemplate) {
				await nextTick()
				selectedTemplate.value = openingTemplate
				templateDialog.value = true
			}
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
		try {
			const options = await call(
				'frappe_whatsapp_core.frontend_api.new_conversation_options',
			)
			catalog.value = { templates: options.templates || [] }
			settings.value = { channels: options.channels || [] }
			newChatContacts.value = options.contacts || []
			newChat.value.channel = options.channels?.[0]?.name || ''
			newChat.value.mode = 'message'
			newChat.value.template = ''
			newDialog.value = true
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'New conversation unavailable',
				detail: errorMessage(error),
				life: 5000,
			})
		}
	}

	function syncNewChatTemplate() {
		if (!openingTemplates.value.some((template) => template.name === newChat.value.template))
			newChat.value.template = ''
	}

	function openRealtimeServiceWindow(message, conversationRow = null) {
		if (
			message?.direction !== 'Inbound' ||
			message?.conversation !== selectedName.value ||
			!detail.value?.outbound
		)
			return
		const inboundAt =
			conversationRow?.last_inbound_at ||
			message.provider_timestamp ||
			message.creation ||
			detail.value.conversation?.last_inbound_at
		if (detail.value.conversation && inboundAt)
			detail.value.conversation.last_inbound_at = inboundAt
		detail.value.outbound.text_allowed = true
		detail.value.outbound.text_ready = Boolean(detail.value.outbound.ready)
	}

	function appendMessage(event) {
		if (event?.changed) {
			refreshCommittedBatch(event)
			return
		}
		if (!event?.conversation || !event.message) return
		const authoritativeRow = event.conversation_row
			? upsertConversationRow(event.conversation_row)
			: null
		if (event.message.message_type === 'reaction') {
			applyReactionMessage(event.message)
			return
		}
		if (event.conversation === selectedName.value && detail.value) {
			const shouldStickToBottom = atMessageBottom.value
			reconcileMessage(event.message)
			openRealtimeServiceWindow(event.message, authoritativeRow)
			if (shouldStickToBottom) scrollToBottom().then(queueVisibleMessages)
			else if (event.message.direction === 'Inbound') hasUnseenMessages.value = true
		}
		const row = authoritativeRow || rows.value.find((item) => item.name === event.conversation)
		if (row) {
			if (
				event.message.direction === 'Inbound' &&
				clearedConversationBadges.has(event.conversation)
			) {
				row.unread_count = Number(row.unread_count || 0) + 1
			}
			if (!authoritativeRow) {
				row.latest_message = event.message
				row.last_message_at = event.message.provider_timestamp
				if (
					event.message.direction === 'Inbound' &&
					event.conversation !== selectedName.value &&
					!clearedConversationBadges.has(event.conversation)
				) {
					row.unread_count = Number(row.unread_count || 0) + 1
				}
				sortConversationRows()
			}
		} else {
			hydrateConversationRow(event.conversation)
		}
	}

	function conversationMatchesFilters(row) {
		const matchesTeam =
			!team.value ||
			(row?.contact_teams || []).some((contactTeam) => contactTeam.name === team.value)
		if (!matchesTeam || !folder.value) return matchesTeam
		const selectedFolder = folders.value.find((item) => item.name === folder.value)
		return (row?.contact_folders || []).some((contactFolder) =>
			selectedFolder?.folder_type === 'Important' || folder.value === 'important'
				? contactFolder.folder_type === 'Important'
				: contactFolder.name === folder.value,
		)
	}

	function sortConversationRows() {
		rows.value = [...rows.value].sort((left, right) => {
			const timestamp = String(right.last_message_at || '').localeCompare(
				String(left.last_message_at || ''),
			)
			return timestamp || String(right.name || '').localeCompare(String(left.name || ''))
		})
	}

	function upsertConversationRow(incoming) {
		if (!incoming?.name) return null
		const existing = rows.value.find((row) => row.name === incoming.name)
		if (!conversationMatchesFilters(incoming)) {
			if (existing) rows.value = rows.value.filter((row) => row.name !== incoming.name)
			return null
		}
		const merged = { ...existing, ...incoming }
		if (clearedConversationBadges.has(incoming.name)) {
			merged.unread_count = Number(existing?.unread_count || 0)
		}
		rows.value = [merged, ...rows.value.filter((row) => row.name !== incoming.name)]
		sortConversationRows()
		return merged
	}

	async function hydrateConversationRow(conversation) {
		if (!conversation || rows.value.some((row) => row.name === conversation)) return
		try {
			const row = await call('frappe_whatsapp_core.inbox.conversation_summary', {
				name: conversation,
			})
			if (row && !rows.value.some((item) => item.name === row.name)) rows.value.unshift(row)
		} catch {
			// A conversation can be outside this operator's team scope. Ignore it.
		}
	}

	function callPreview(callRow) {
		const direction = callRow?.direction === 'Inbound' ? 'Incoming' : 'Outgoing'
		const status = String(callRow?.status || '').toLowerCase()
		if (['missed', 'reject', 'rejected', 'failed'].includes(status))
			return `${direction} call · ${status[0].toUpperCase()}${status.slice(1)}`
		if (['terminate', 'terminated', 'ended'].includes(status))
			return `${direction} call · Completed`
		if (['accept', 'accepted', 'connected'].includes(status))
			return `${direction} call · Answered`
		return `${direction} call`
	}

	function upsertTimelineCall(event) {
		const callRow = event?.call
		if (!callRow?.conversation) return
		if (callRow.conversation === selectedName.value && detail.value) {
			if (!Array.isArray(detail.value.calls)) detail.value.calls = []
			const existing = detail.value.calls.findIndex(
				(item) =>
					(callRow.name && item.name === callRow.name) ||
					(callRow.call_id && item.call_id === callRow.call_id),
			)
			const merged =
				existing >= 0 ? { ...detail.value.calls[existing], ...callRow } : callRow
			if (existing >= 0) detail.value.calls.splice(existing, 1, merged)
			else detail.value.calls.push(merged)
			if (existing < 0 && atMessageBottom.value) nextTick().then(() => scrollToBottom())
		}
		const row = rows.value.find((item) => item.name === callRow.conversation)
		if (!row) {
			hydrateConversationRow(callRow.conversation)
			return
		}
		const activityAt =
			callRow.ended_at || callRow.started_at || callRow.timeline_at || callRow.modified
		if (
			!row.last_message_at ||
			timelineTimestamp({ timeline_at: activityAt }) >=
				timelineTimestamp({ timeline_at: row.last_message_at })
		) {
			row.last_message_at = activityAt
			row.latest_message = {
				name: callRow.name,
				call_id: callRow.call_id,
				message_type: 'call',
				direction: callRow.direction,
				body: callPreview(callRow),
				provider_timestamp: activityAt,
				delivery_status: callRow.status,
			}
			sortConversationRows()
		}
	}

	async function refreshVisibleCalls() {
		if (!detail.value || !selectedName.value) return
		const conversation = selectedName.value
		const currentDetail = detail.value
		try {
			const result = await call('frappe_whatsapp_core.calling.conversation_call_history', {
				conversation,
				limit: 100,
			})
			if (conversation === selectedName.value && detail.value === currentDetail)
				currentDetail.calls = result?.rows || []
		} catch {
			// A later scoped call event or reconnect will retry this projection.
		}
	}

	function updateMessageStatus(event) {
		if (event?.changed) {
			refreshCommittedBatch(event)
			return
		}
		if (event?.conversation !== selectedName.value || !detail.value) return
		const message = detail.value.messages.find((item) => item.name === event.message)
		if (message) {
			message.delivery_status = event.delivery_status
			message.provider_message_id = event.provider_message_id || message.provider_message_id
			if (event.failure !== undefined) message.failure = event.failure
		}
	}

	function updateConversationReader(event) {
		if (event?.changed) {
			refreshCommittedBatch(event)
			return
		}
		if (event?.conversation_row) upsertConversationRow(event.conversation_row)
		if (event?.conversation !== selectedName.value || !detail.value || !event.user) return
		const previous = (detail.value.readers || []).find((reader) => reader.user === event.user)
		const staleCursor = previous && compareCursorPosition(event, previous) < 0
		const updated = staleCursor
			? previous
			: {
					...previous,
					user: event.user,
					last_read_message: event.last_read_message || null,
					last_read_at: event.last_read_at,
					last_read_creation: event.last_read_creation || null,
					full_name:
						previous?.full_name ||
						(session.user?.name === event.user ? session.user?.full_name : '') ||
						event.full_name ||
						event.user,
					display_name: previous?.display_name || event.display_name || event.full_name,
					user_image: previous?.user_image || event.user_image || '',
				}
		if (!staleCursor) {
			const readers = (detail.value.readers || []).filter(
				(reader) => reader.user !== event.user,
			)
			detail.value.readers = [updated, ...readers]
			if (session.user?.name === event.user) detail.value.current_user_read = updated
		}
		const exactMessages = new Set(event.messages || [])
		for (const message of detail.value.messages || []) {
			if (!exactMessages.has(message.name)) continue
			const readBy = (message.read_by || []).filter((reader) => reader.user !== event.user)
			readBy.push({
				...updated,
				read_at: event.read_at || new Date().toISOString(),
			})
			message.read_by = readBy
		}
	}

	function mergeCommittedMessage(message, { allowAppend = true } = {}) {
		if (!detail.value || !message || message.conversation !== selectedName.value) return
		if (message.message_type === 'reaction') {
			applyReactionMessage(message)
			return
		}
		const index = detail.value.messages.findIndex((item) => item.name === message.name)
		if (index >= 0) {
			detail.value.messages.splice(index, 1, {
				...detail.value.messages[index],
				...message,
			})
		} else if (allowAppend) {
			detail.value.messages.push({ bookmarked: false, ...message })
		}
	}

	function isNewerMessage(message, current) {
		if (!current) return true
		const incoming = new Date(message.provider_timestamp || message.creation || 0).getTime()
		const existing = new Date(current.provider_timestamp || current.creation || 0).getTime()
		return !Number.isFinite(existing) || (Number.isFinite(incoming) && incoming >= existing)
	}

	function refreshCommittedBatch(event) {
		pendingBatchEvents.push(event || {})
		// Coalesce one bounded window without postponing refresh indefinitely
		// while a high-volume account is receiving continuous events.
		if (batchRefreshTimer !== null) return
		batchRefreshTimer = window.setTimeout(async () => {
			batchRefreshTimer = null
			const shouldStickToBottom = atMessageBottom.value
			const events = pendingBatchEvents.splice(0)
			const changesByMessage = new Map()
			const conversationRowsByName = new Map()
			const kinds = new Set()
			const conversations = new Set()
			let needsCompatibilityReload = false
			for (const batch of events) {
				if (!Array.isArray(batch?.message_changes)) needsCompatibilityReload = true
				for (const kind of batch?.kinds || []) kinds.add(kind)
				for (const conversation of batch?.conversations || [])
					conversations.add(conversation)
				for (const row of batch?.conversation_rows || []) {
					if (row?.name) conversationRowsByName.set(row.name, row)
				}
				for (const change of batch?.message_changes || []) {
					const name = change?.message?.name
					if (!name) continue
					const previous = changesByMessage.get(name)
					changesByMessage.set(name, {
						...previous,
						...change,
						status:
							previous?.status === 'created' || change.status === 'created'
								? 'created'
								: change.status,
						message: { ...previous?.message, ...change.message },
					})
				}
			}
			for (const row of conversationRowsByName.values()) upsertConversationRow(row)
			const changes = [...changesByMessage.values()]
			if (changes.length) {
				let selectedChanged = false
				let latestSelectedInbound = null
				for (const change of changes) {
					const message = change?.message
					if (!message?.conversation) continue
					const isCreated = change.status === 'created'
					if (message.message_type === 'reaction') {
						if (isCreated && message.conversation === selectedName.value)
							applyReactionMessage(message)
						continue
					}
					if (message.conversation === selectedName.value) {
						const alreadyLoaded = detail.value?.messages?.some(
							(item) => item.name === message.name,
						)
						if (isCreated || alreadyLoaded) {
							mergeCommittedMessage(message, { allowAppend: isCreated })
							selectedChanged = true
						}
						if (isCreated && message.direction === 'Inbound')
							openRealtimeServiceWindow(
								message,
								conversationRowsByName.get(message.conversation),
							)
						if (isCreated && message.direction === 'Inbound')
							latestSelectedInbound = message
					}
					const row = rows.value.find((item) => item.name === message.conversation)
					if (!row) continue
					if (
						isCreated &&
						message.direction === 'Inbound' &&
						clearedConversationBadges.has(message.conversation)
					)
						row.unread_count = Number(row.unread_count || 0) + 1
					if (conversationRowsByName.has(message.conversation)) continue
					if (
						(isCreated && isNewerMessage(message, row.latest_message)) ||
						(!isCreated && row.latest_message?.name === message.name)
					) {
						row.latest_message = { ...row.latest_message, ...message }
						row.last_message_at = message.provider_timestamp || message.creation
						sortConversationRows()
					}
					if (
						isCreated &&
						message.direction === 'Inbound' &&
						message.conversation !== selectedName.value &&
						!clearedConversationBadges.has(message.conversation)
					)
						row.unread_count = Number(row.unread_count || 0) + 1
				}
				if (selectedChanged && shouldStickToBottom) await scrollToBottom()
				else if (latestSelectedInbound) hasUnseenMessages.value = true
				if (selectedChanged) queueVisibleMessages()
				if (!needsCompatibilityReload) return
			}
			if (
				kinds.size &&
				![...kinds].some((kind) => ['message', 'status', 'edit', 'revoke'].includes(kind))
			)
				return
			// Compatibility for events from an older worker during rolling deploys.
			await loadRows({ silent: true })
			if (
				selectedName.value &&
				(!conversations.size || conversations.has(selectedName.value))
			) {
				const addedInbound = await refreshVisibleMessages()
				if (!shouldStickToBottom && addedInbound) hasUnseenMessages.value = true
				if (shouldStickToBottom) await scrollToBottom()
			}
		}, 120)
	}

	async function refreshVisibleMessages() {
		if (!detail.value || !selectedName.value) return false
		const conversation = selectedName.value
		const currentDetail = detail.value
		const visible = currentDetail.messages || []
		const committed = visible.filter((message) => !message.optimistic)
		const newest = committed.reduce(
			(current, message) =>
				!current || compareCursorPosition(message, current) > 0 ? message : current,
			null,
		)
		try {
			const [refreshed, newer] = await Promise.all([
				call('frappe_whatsapp_core.workspace_api.refresh_messages', {
					conversation,
					message_names: committed.map((message) => message.name),
				}),
				newest
					? call('frappe_whatsapp_core.workspace_api.list_messages', {
							conversation,
							after: newest.provider_timestamp,
							after_creation: newest.creation,
							after_name: newest.name,
							limit: 100,
						})
					: Promise.resolve({ rows: [], has_more: false }),
			])
			if (conversation !== selectedName.value || detail.value !== currentDetail) return false
			const refreshedByName = new Map(
				(refreshed.rows || []).map((message) => [message.name, message]),
			)
			const merged = visible.map((message) =>
				refreshedByName.has(message.name)
					? { ...message, ...refreshedByName.get(message.name) }
					: message,
			)
			const known = new Set(merged.map((message) => message.name))
			const added = []
			for (const message of newer.rows || []) {
				if (known.has(message.name)) continue
				known.add(message.name)
				merged.push(message)
				added.push(message)
			}
			merged.sort((left, right) => compareCursorPosition(left, right))
			currentDetail.messages = merged
			messagePage.value = {
				...messagePage.value,
				has_more_newer: Boolean(newer.has_more),
				next_after: newer.next_after || null,
				next_after_creation: newer.next_after_creation || null,
				next_after_name: newer.next_after_name || null,
			}
			await nextTick()
			queueVisibleMessages()
			return added.some((message) => message.direction === 'Inbound')
		} catch {
			// Reconnect and later durable invalidations will retry this projection.
			return false
		}
	}

	async function updateStatus(status) {
		const conversation = selectedName.value
		try {
			await call('frappe_whatsapp_core.inbox.update_conversation', {
				name: conversation,
				status,
			})
			if (conversation !== selectedName.value || !detail.value) return
			detail.value.conversation.status = status
			const row = rows.value.find((item) => item.name === conversation)
			if (row) row.status = status
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Conversation not updated',
				detail: errorMessage(error, 'Unable to update the conversation status.'),
				life: 5000,
			})
		}
	}

	async function refreshContactSummary() {
		const identity = detail.value?.identity?.name
		if (!identity) return
		summaryRefreshing.value = true
		try {
			const summary = await call('frappe_whatsapp_core.frontend_api.contact_summary', {
				identity,
				refresh: 1,
			})
			if (detail.value?.identity?.name === identity) detail.value.contact_summary = summary
			toast.add({ severity: 'success', summary: 'Contact summary updated', life: 2500 })
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Summary not updated',
				detail: errorMessage(error, 'Unable to refresh the contact summary.'),
				life: 5000,
			})
		} finally {
			summaryRefreshing.value = false
		}
	}

	async function loadFolders() {
		try {
			folders.value = await call('frappe_whatsapp_core.customer_workspace.contact_folders')
			if (
				folder.value &&
				folder.value !== 'important' &&
				!folders.value.some((item) => item.name === folder.value)
			) {
				folder.value = ''
			}
		} catch (error) {
			toast.add({
				severity: 'warn',
				summary: 'Personal folders unavailable',
				detail: errorMessage(error),
				life: 4000,
			})
		}
	}

	async function createContactFolder() {
		if (!folderName.value.trim()) return
		savingFolder.value = true
		try {
			const created = await call(
				'frappe_whatsapp_core.customer_workspace.create_contact_folder',
				{ folder_name: folderName.value, color: folderColor.value },
			)
			folders.value.push(created)
			folderName.value = ''
			folderDialog.value = false
			toast.add({
				severity: 'success',
				summary: 'Contact folder created',
				detail: 'Open a customer and add it from My folders.',
				life: 3500,
			})
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Folder not created',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			savingFolder.value = false
		}
	}

	async function setContactFolder({ folder: selectedFolder, enabled }) {
		const identity = detail.value?.identity?.name
		if (!identity || !selectedFolder?.name) return
		try {
			const result = await call(
				'frappe_whatsapp_core.customer_workspace.set_contact_folder',
				{ identity, folder: selectedFolder.name, enabled: enabled ? 1 : 0 },
			)
			const canonical =
				result.folder_details ||
				folders.value.find((item) => item.name === result.folder) ||
				folders.value.find((item) => item.folder_type === selectedFolder.folder_type) ||
				selectedFolder
			applyFolderMembership(identity, canonical, enabled)
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Folder not updated',
				detail: errorMessage(error),
				life: 4500,
			})
		}
	}

	function applyFolderMembership(identity, canonical, enabled) {
		if (!identity || !canonical?.name) return
		let folderMatched = false
		folders.value = folders.value.map((item) => {
			if (
				item.name !== canonical.name &&
				(!canonical.folder_type || item.folder_type !== canonical.folder_type)
			)
				return item
			folderMatched = true
			return { ...item, ...canonical }
		})
		if (!folderMatched) folders.value.push(canonical)
		const apply = (target) => {
			if (!target || target.remote_identity !== identity) return
			const current = (target.contact_folders || []).filter(
				(item) =>
					item.name !== canonical.name && item.folder_type !== canonical.folder_type,
			)
			target.contact_folders = enabled ? [...current, canonical] : current
		}
		rows.value.forEach(apply)
		if (detail.value?.identity?.name === identity) {
			const current = (detail.value.contact_folders || []).filter(
				(item) =>
					item.name !== canonical.name && item.folder_type !== canonical.folder_type,
			)
			detail.value.contact_folders = enabled ? [...current, canonical] : current
		}
		if (folder.value && !enabled)
			rows.value = rows.value.filter((row) => conversationMatchesFilters(row))
	}

	async function refreshContactFolders(event) {
		if (event?.identity && event?.folder_details) {
			applyFolderMembership(event.identity, event.folder_details, Boolean(event.enabled))
			if (event.enabled && folder.value) {
				const matchesActiveFolder =
					folder.value === event.folder_details.name ||
					(folder.value === 'important' &&
						event.folder_details.folder_type === 'Important')
				if (matchesActiveFolder) {
					await Promise.all(
						(event.conversations || [])
							.filter(
								(conversation) =>
									!rows.value.some((row) => row.name === conversation),
							)
							.map((conversation) => hydrateConversationRow(conversation)),
					)
				}
			}
			return
		}
		await loadFolders()
		if (!event?.identity) return
		const affected = rows.value.filter((row) => row.remote_identity === event.identity)
		let updatedFolders = null
		for (const row of affected) {
			try {
				const updated = await call('frappe_whatsapp_core.inbox.conversation_summary', {
					name: row.name,
				})
				updatedFolders = updated?.contact_folders || updatedFolders
				upsertConversationRow(updated)
			} catch {
				// Access can change between the notification and this targeted refresh.
			}
		}
		if (detail.value?.identity?.name === event.identity)
			detail.value.contact_folders = updatedFolders || detail.value.contact_folders || []
	}

	async function scrollToBottom(smooth = false) {
		await nextTick()
		if (stream.value) {
			if (smooth && stream.value.scrollTo) {
				stream.value.scrollTo({ top: stream.value.scrollHeight, behavior: 'smooth' })
			} else {
				stream.value.scrollTop = stream.value.scrollHeight
			}
			hasUnseenMessages.value = false
			updateMessageBottomState()
			rememberMessageScroll()
		}
	}

	async function loadLatestMessages() {
		if (!detail.value || !stream.value || jumpingToLatest.value) return
		const conversation = selectedName.value
		const currentDetail = detail.value
		jumpingToLatest.value = true
		try {
			const page = await call('frappe_whatsapp_core.workspace_api.list_messages', {
				conversation,
				limit: 20,
			})
			if (conversation !== selectedName.value || detail.value !== currentDetail) return
			currentDetail.messages = [...page.rows].reverse()
			messagePage.value = {
				has_more: page.has_more,
				has_more_newer: false,
				next_before: page.next_before,
				next_before_creation: page.next_before_creation,
				next_before_name: page.next_before_name,
				next_after: null,
				next_after_creation: null,
				next_after_name: null,
			}
			await scrollToBottom(true)
			await new Promise((resolve) => window.setTimeout(resolve, 400))
			// Smooth scrolling can be interrupted while the latest page replaces the
			// current DOM. Finish with an exact position so "New messages" always
			// lands on the actual final message, even with a long conversation.
			if (conversation !== selectedName.value || detail.value !== currentDetail) return
			await scrollToBottom()
			updateMessageBottomState()
			queueVisibleMessages()
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Could not reach the latest message',
				detail: errorMessage(error),
				life: 3500,
			})
		} finally {
			jumpingToLatest.value = false
		}
	}

	watch(selectedName, (name, previousName) => {
		if (previousName) leaveConversationPresence(previousName)
		enterConversationPresence(name)
		rememberMessageScroll(previousName)
		discardPendingReadMessages(previousName)
		locallyReadMessages.clear()
		hasUnseenMessages.value = false
		atMessageBottom.value = true
		loadDetail(name)
		replyTo.value = null
		contextOpen.value = false
		stopTypingSession()
		closeMessageSearch()
	})
	watch(messageSearch, () => {
		clearTimeout(messageSearchTimer)
		messageSearchTimer = setTimeout(runMessageSearch, 300)
	})
	watch(search, () => {
		window.clearTimeout(conversationSearchTimer)
		conversationSearchTimer = window.setTimeout(() => loadRows({ silent: true }), 220)
	})
	watch(team, async () => {
		await loadRows()
	})
	watch(folder, async () => {
		await loadRows()
	})
	watch(viewMode, (mode) => localStorage.setItem('whatsapp:conversation-view', mode))
	onMounted(async () => {
		window.addEventListener('keydown', handleGlobalKeydown)
		window.addEventListener('focus', handleReadVisibilityChange)
		window.addEventListener('blur', handleReadVisibilityChange)
		document.addEventListener('visibilitychange', handleReadVisibilityChange)
		document.addEventListener('visibilitychange', handlePresenceVisibilityChange)
		await Promise.all([loadFolders(), loadRows()])
		clearConversationBadge(selectedName.value)
		if (selectedName.value) await loadDetail(selectedName.value)
		enterConversationPresence(selectedName.value)
		const site = session.boot?.site
		unsubscribers.push(
			subscribe(site, 'whatsapp_core_message', appendMessage),
			subscribe(site, 'whatsapp_core_message_status', updateMessageStatus),
			subscribe(site, 'whatsapp_core_call', upsertTimelineCall),
			subscribe(site, 'whatsapp_core_conversation_read', updateConversationReader),
			subscribe(site, 'whatsapp_core_conversation_presence', applyConversationPresence),
			subscribe(site, 'whatsapp_core_batch_committed', refreshCommittedBatch),
			subscribe(site, 'whatsapp_core_contact', refreshDirectoryPresentations),
			subscribe(site, 'whatsapp_core_team', refreshDirectoryPresentations),
			subscribe(site, 'whatsapp_core_contact_folder', refreshContactFolders),
			subscribeConnection(site, async (status) => {
				if (status !== 'connected') return
				if (!realtimeConnectedOnce) {
					realtimeConnectedOnce = true
					return
				}
				// Socket.IO does not replay events missed while a browser was offline.
				// Reconcile from durable Core projections after every reconnect.
				await loadRows({ silent: true })
				if (selectedName.value)
					await Promise.all([refreshVisibleMessages(), refreshVisibleCalls()])
			}),
		)
	})
	onBeforeUnmount(() => {
		window.removeEventListener('keydown', handleGlobalKeydown)
		window.removeEventListener('focus', handleReadVisibilityChange)
		window.removeEventListener('blur', handleReadVisibilityChange)
		document.removeEventListener('visibilitychange', handleReadVisibilityChange)
		document.removeEventListener('visibilitychange', handlePresenceVisibilityChange)
		rememberMessageScroll()
		clearTimeout(messageSearchTimer)
		clearTimeout(conversationSearchTimer)
		leaveConversationPresence()
		stopTypingSession()
		window.clearTimeout(batchRefreshTimer)
		batchRefreshTimer = null
		discardPendingReadMessages()
		pendingBatchEvents = []
		unsubscribers.forEach((unsubscribe) => unsubscribe())
	})
</script>

<template>
	<div class="inbox-page">
		<section
			:class="[
				'inbox-workbench',
				{
					'mobile-chat-open': detail,
					'context-open': detail && contextOpen,
				},
			]"
			:style="workbenchStyle"
		>
			<aside class="list-panel">
				<InboxSidebarControls
					v-model:search="search"
					v-model:mode="listMode"
					v-model:team="team"
					v-model:folder="folder"
					:folders="folders"
					:loading="loading"
					:can-manage="canManage"
					@refresh="loadRows"
					@new-chat="openNewChat"
					@new-folder="folderDialog = true"
				/>
				<div v-if="loading" class="list-skeleton" aria-label="Loading conversations">
					<div v-for="index in 7" :key="index" class="conversation-skeleton">
						<Skeleton shape="circle" size="42px" />
						<span
							><Skeleton width="58%" height="11px" /><Skeleton height="9px"
						/></span>
					</div>
				</div>
				<div v-else-if="listError" class="panel-error" role="alert">
					<ShieldAlert :size="22" />
					<strong>Conversations unavailable</strong>
					<span>{{ listError }}</span>
					<Button label="Retry" size="small" outlined @click="loadRows" />
				</div>
				<ConversationList
					v-else
					:rows="filteredRows"
					:selected="selectedName"
					:restore-scroll="listScrollTop"
					@select="selectConversation"
					@scroll-position="rememberListScroll"
					@load-more="loadMoreRows"
				/>
				<div v-if="loadingMoreRows" class="older-loading">Loading conversations…</div>
			</aside>
			<InboxResizeHandle
				:width="listPaneWidth"
				:max-width="listPaneMaxWidth"
				@resize="resizeListPane"
				@reset="resizeListPane(360)"
			/>

			<main class="chat-panel">
				<div
					v-if="detailLoading"
					class="detail-skeleton"
					aria-label="Loading conversation"
				>
					<Skeleton width="44%" height="58px" border-radius="12px" />
					<Skeleton width="62%" height="76px" border-radius="12px" />
					<Skeleton width="38%" height="54px" border-radius="12px" />
				</div>
				<div v-else-if="detailError" class="empty-chat error-chat" role="alert">
					<ShieldAlert :size="38" />
					<strong>Conversation unavailable</strong>
					<span>{{ detailError }}</span>
					<Button label="Try again" outlined @click="loadDetail(selectedName)" />
				</div>
				<div v-else-if="!detail" class="empty-chat">
					<span class="empty-chat-icon"><MessageSquarePlus :size="28" /></span>
					<strong>Select a conversation</strong>
					<span
						>Choose a customer from the shared inbox to review messages, calls and
						context.</span
					>
				</div>
				<template v-else>
					<ConversationHeader
						:display-name="detail.display_name"
						:identity="detail.contact_presentation?.secondary_text || ''"
						:avatar="detail.contact_presentation?.avatar || ''"
						:teams="detailTeams"
						:status="detail.conversation.status"
						:viewers="conversationViewers"
						:context-open="contextOpen"
						:view-mode="viewMode"
						@back="closeMobileConversation"
						@search="toggleMessageSearch"
						@toggle-context="contextOpen = !contextOpen"
						@update:view-mode="viewMode = $event"
					/>
					<ConversationSummaryPanel
						v-if="viewMode === 'summary'"
						:data="detail"
						:can-manage="canManage"
						:loading="summaryRefreshing"
						@refresh="refreshContactSummary"
					/>
					<template v-else>
						<div v-if="messageSearchOpen" class="message-search-bar">
							<Search :size="15" />
							<InputText
								ref="messageSearchInput"
								v-model="messageSearch"
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
						<MessageStreamViewport ref="stream" @scroll="handleStreamScroll">
							<div v-if="messageSearch.trim()" class="search-results">
								<div v-if="messageSearching" class="older-loading">Searching…</div>
								<div v-else-if="!messageSearchRows.length" class="search-empty">
									No matching messages
								</div>
								<MessageBubble
									v-for="message in messageSearchRows"
									:key="message.name"
									:message="message"
									:message-index="providerMessageMap"
									:contact-name="detail.display_name"
									:readers="readersByMessage.get(message.name) || []"
									@reply="selectReply"
									@quote="openQuotedMessage"
									@retry="retryMessage"
									@menu="openMessageMenu"
								/>
							</div>
							<template v-else>
								<div v-if="loadingOlder" class="older-loading">
									Loading older messages…
								</div>
								<Button
									v-else-if="messagePage.has_more"
									class="older-loading older-button"
									unstyled
									@click="loadOlderMessages"
								>
									Load older messages
								</Button>
								<details
									v-for="topic in topics"
									:key="topic.name"
									class="topic-group"
								>
									<summary>
										<span>
											<small>{{ topic.category || 'AI topic' }}</small>
											<strong>{{ topic.title }}</strong>
											<p>
												{{
													topic.summary ||
													'Open to review grouped messages.'
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
											:message-index="providerMessageMap"
											:contact-name="detail.display_name"
											:readers="readersByMessage.get(message.name) || []"
											@reply="selectReply"
											@quote="openQuotedMessage"
											@retry="retryMessage"
											@menu="openMessageMenu"
										/>
									</div>
								</details>
								<div v-if="timelineItems.length" class="ungrouped">
									<div v-if="topics.length" class="section-label">
										Recent conversation activity
									</div>
									<template v-for="item in timelineItems" :key="item.key">
										<CallTimelineEvent
											v-if="item.kind === 'call'"
											:call="item.value"
										/>
										<MessageBubble
											v-else
											:message="item.value"
											:message-index="providerMessageMap"
											:contact-name="detail.display_name"
											:readers="readersByMessage.get(item.value.name) || []"
											@reply="selectReply"
											@quote="openQuotedMessage"
											@retry="retryMessage"
											@menu="openMessageMenu"
										/>
									</template>
								</div>
								<Button
									v-if="messagePage.has_more_newer"
									class="older-loading older-button newer-button"
									unstyled
									:disabled="loadingNewer"
									@click="loadNewerMessages"
								>
									{{
										loadingNewer
											? 'Loading newer messages…'
											: 'Load newer messages'
									}}
								</Button>
							</template>
						</MessageStreamViewport>
						<Button
							v-if="
								messagePage.has_more_newer || !atMessageBottom || hasUnseenMessages
							"
							class="new-messages-button"
							unstyled
							:data-unseen="hasUnseenMessages ? 'true' : 'false'"
							:disabled="jumpingToLatest"
							:aria-label="
								hasUnseenMessages || messagePage.has_more_newer
									? 'Jump to new messages'
									: 'Scroll to bottom'
							"
							@click="loadLatestMessages"
						>
							<ArrowDown :size="15" />
							{{
								jumpingToLatest
									? 'Loading latest…'
									: hasUnseenMessages || messagePage.has_more_newer
										? 'New messages'
										: 'Scroll to bottom'
							}}
						</Button>
						<MessageComposer
							v-if="textReady"
							v-model="draft"
							:reply-to="replyTo"
							@send="sendText"
							@emoji="addEmoji"
							@media="richDialog = true"
							@cancel-reply="replyTo = null"
							@typing="noteTyping"
							@blur="stopTypingSession"
						/>
						<footer v-else class="template-gate">
							<ShieldAlert :size="18" />
							<div>
								<strong>Template required</strong>
								<span>{{
									detail.outbound.reasons?.join(' · ') ||
									'The 24-hour service window is closed.'
								}}</span>
							</div>
							<Button
								label="Choose template"
								:loading="richSending"
								@click="templateDialog = true"
							/>
						</footer>
					</template>
				</template>
			</main>

			<ConversationContext
				v-if="detail && contextOpen"
				:data="detail"
				:can-manage="canManage"
				:folders="folders"
				@status="updateStatus"
				@refresh-summary="refreshContactSummary"
				@avatar-changed="refreshDirectoryPresentations"
				@folder="setContactFolder"
			/>
		</section>

		<AppDialog v-model:visible="folderDialog" modal header="Create contact folder">
			<div class="dialog-form folder-dialog-form">
				<div class="folder-dialog-icon"><FolderPlus :size="21" /></div>
				<label>
					Folder name
					<InputText
						v-model="folderName"
						maxlength="80"
						placeholder="For example: Priority customers"
					/>
				</label>
				<label>
					Folder colour
					<input v-model="folderColor" type="color" aria-label="Folder colour" />
				</label>
				<small>Folders are private to your user and never change team access.</small>
			</div>
			<template #footer>
				<Button label="Cancel" text @click="folderDialog = false" />
				<Button
					label="Create folder"
					:loading="savingFolder"
					:disabled="!folderName.trim()"
					@click="createContactFolder"
				/>
			</template>
		</AppDialog>

		<TemplateSendDialog
			v-if="detail"
			v-model:visible="templateDialog"
			:templates="detail.templates"
			:loading="richSending"
			:initial-template="selectedTemplate"
			:conversation="selectedName"
			@send="sendTemplate"
		/>

		<AppDialog
			ref="newDialogRef"
			v-model:visible="newDialog"
			modal
			header="Start WhatsApp conversation"
			class="new-chat-dialog"
			@show="focusDialogControl(newDialogRef, '[role=combobox]')"
		>
			<div class="dialog-form">
				<label
					>Channel<ChannelSelect
						v-model="newChat.channel"
						aria-label="WhatsApp channel"
						:options="settings.channels.filter((item) => item.enabled)"
						option-value="name"
						@change="syncNewChatTemplate"
				/></label>
				<label
					>Contact<ContactSelect
						v-model="newChat.identity"
						:options="newChatContacts"
						@update:model-value="newChat.phone_number = ''"
				/></label>
				<label
					>Or enter a WhatsApp number<InputText
						v-model="newChat.phone_number"
						placeholder="Country code and number"
						@input="newChat.identity = ''"
				/></label>
				<label v-if="!newChat.identity"
					>Display name<InputText v-model="newChat.display_name" placeholder="Optional"
				/></label>
				<label
					>Start with<Select
						v-model="newChat.mode"
						aria-label="Conversation opening method"
						:options="newConversationModes"
						option-label="label"
						option-value="value"
				/></label>
				<label v-if="newChat.mode === 'template'"
					>Approved opening template<TemplateSelect
						v-model="newChat.template"
						:options="openingTemplates"
				/></label>
				<small v-else>
					The chat opens directly. WhatsApp permits free-form messages while the 24-hour
					customer service window is open.
				</small>
			</div>
			<template #footer>
				<Button label="Cancel" text @click="newDialog = false" />
				<Button
					:label="newChat.mode === 'template' ? 'Start with template' : 'Open chat'"
					:loading="starting"
					:disabled="
						!newChat.channel ||
						(!newChat.identity && !newChat.phone_number.trim()) ||
						(newChat.mode === 'template' && !newChat.template)
					"
					@click="startConversation"
				/>
			</template>
		</AppDialog>

		<AppDialog
			ref="richDialogRef"
			v-model:visible="richDialog"
			modal
			header="Send a WhatsApp message"
			class="rich-dialog"
			@show="focusDialogControl(richDialogRef, '[role=combobox]')"
		>
			<div class="dialog-form">
				<label
					>Type<Select
						v-model="richForm.type"
						aria-label="WhatsApp message type"
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
				<ContactMessageEditor
					v-else-if="richForm.type === 'contacts'"
					v-model="richForm.contacts"
				/>
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
		</AppDialog>

		<AppDialog
			v-model:visible="messageInfoOpen"
			modal
			header="Message info"
			class="message-info-dialog"
		>
			<div v-if="messageInfo" class="message-info-grid">
				<div>
					<span>Direction</span><strong>{{ messageInfo.direction || '—' }}</strong>
				</div>
				<div>
					<span>Type</span><strong>{{ messageInfo.message_type || '—' }}</strong>
				</div>
				<div>
					<span>Status</span><strong>{{ messageInfo.delivery_status || '—' }}</strong>
				</div>
				<div>
					<span>Time</span>
					<strong>{{ formatInfoTime(messageInfo.provider_timestamp) }}</strong>
				</div>
				<div v-if="messageInfo.direction === 'Outbound'">
					<span>Sent by</span>
					<strong>{{
						messageInfo.sender_name || messageInfo.owner || 'Team member'
					}}</strong>
				</div>
				<div class="message-info-id">
					<span>WhatsApp message ID</span>
					<strong>{{ messageInfo.provider_message_id || 'Pending assignment' }}</strong>
				</div>
			</div>
			<template #footer>
				<Button label="Close" @click="messageInfoOpen = false" />
			</template>
		</AppDialog>

		<MessageActionMenu
			:visible="Boolean(messageMenu)"
			:position="messageMenuPosition"
			:reactions="quickReactions"
			:can-reply="
				Boolean(
					messageMenu?.provider_message_id &&
					!messageMenu.provider_message_id.startsWith('local:'),
				)
			"
			:can-download="
				Boolean(messageMenu && isMediaMessage(messageMenu) && messageMenu.media_url)
			"
			@close="closeMessageMenu"
			@react="reactToMessage"
			@reply="replyFromMenu"
			@info="showMessageInfo"
			@download="downloadMedia"
		/>
	</div>
</template>

<style scoped>
	.inbox-page {
		height: 100dvh;
		padding: 0;
		display: flex;
		flex-direction: column;
		background: var(--wa-surface);
		font-family: 'Cabinet Grotesk', Inter, 'Segoe UI', Helvetica, Arial, sans-serif;
		font-size: 14px;
		-webkit-font-smoothing: antialiased;
	}
	.inbox-workbench {
		min-height: 0;
		flex: 1;
		display: grid;
		grid-template-columns: var(--conversation-pane-width, 360px) 5px minmax(0, 1fr);
		overflow: hidden;
	}
	.inbox-workbench.context-open {
		grid-template-columns: var(--conversation-pane-width, 340px) 5px minmax(0, 1fr) minmax(
				270px,
				310px
			);
	}
	.list-panel,
	.chat-panel {
		position: relative;
		min-width: 0;
	}
	.chat-panel {
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.list-panel {
		min-height: 0;
		display: grid;
		grid-template-rows: auto auto auto minmax(0, 1fr);
		overflow: hidden;
		border-right: 1px solid var(--wa-border);
	}
	.list-skeleton {
		padding: 3px 0;
		overflow: hidden;
	}
	.conversation-skeleton {
		display: grid;
		grid-template-columns: 42px minmax(0, 1fr);
		align-items: center;
		gap: 11px;
		padding: 12px 14px;
		border-bottom: 1px solid var(--wa-border-soft);
	}
	.conversation-skeleton span {
		display: grid;
		gap: 8px;
	}
	.detail-skeleton {
		min-height: 0;
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 14px;
		padding: 80px 22px 22px;
		background:
			radial-gradient(
				circle at 90% 0,
				color-mix(in srgb, var(--wa-primary) 9%, transparent),
				transparent 36%
			),
			var(--wa-chat-bg);
	}
	.detail-skeleton > :nth-child(2) {
		align-self: flex-end;
	}
	.loading-state,
	.empty-chat {
		flex: 1;
		display: grid;
		place-content: center;
		justify-items: center;
		gap: 8px;
		color: var(--wa-muted);
		font-size: 13px;
	}
	.panel-error {
		min-height: 240px;
		padding: 22px;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: var(--wa-danger);
		text-align: center;
	}
	.panel-error span,
	.error-chat span {
		max-width: 320px;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.5;
	}
	.panel-error .p-button,
	.error-chat .p-button {
		margin-top: 6px;
	}
	.error-chat > svg {
		color: var(--wa-danger);
	}
	.empty-chat strong {
		color: var(--wa-text);
		font-size: 15px;
	}
	.empty-chat-icon {
		width: 58px;
		height: 58px;
		display: grid;
		place-items: center;
		margin-bottom: 4px;
		border: 1px solid color-mix(in srgb, var(--wa-primary) 20%, var(--wa-border));
		border-radius: var(--wa-radius-card);
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		box-shadow: 0 12px 28px color-mix(in srgb, var(--wa-primary) 10%, transparent);
	}
	.empty-chat span {
		max-width: 310px;
		text-align: center;
		line-height: 1.5;
	}
	.message-search-bar {
		display: flex;
		align-items: center;
	}
	.message-search-bar {
		gap: 8px;
		padding: 7px 11px;
		border-bottom: 1px solid var(--wa-border);
		color: var(--wa-muted);
		background: var(--wa-surface);
	}
	.message-search-bar :deep(input) {
		min-width: 0;
		flex: 1;
		border: 0;
		box-shadow: none;
	}
	.new-messages-button {
		position: absolute;
		right: 18px;
		bottom: 76px;
		z-index: 3;
		display: inline-flex;
		min-height: 44px;
		align-items: center;
		gap: 6px;
		padding: 7px 11px;
		border: 1px solid color-mix(in srgb, var(--wa-green) 35%, var(--wa-border));
		border-radius: 999px;
		background: var(--wa-surface);
		box-shadow: 0 6px 18px rgba(16, 35, 29, 0.16);
		color: var(--wa-success);
		font: inherit;
		font-size: 12px;
		font-weight: 700;
		cursor: pointer;
	}
	.new-messages-button:disabled {
		opacity: 0.7;
		cursor: wait;
	}
	.ungrouped,
	.topic-messages,
	.search-results {
		min-width: 0;
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 8px;
	}
	.search-empty {
		margin: auto;
		padding: 20px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.section-label {
		margin: 8px 0;
		color: var(--wa-muted);
		font-size: 12px;
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
		color: var(--wa-muted);
		background: color-mix(in srgb, var(--wa-surface) 92%, transparent);
		font: inherit;
		font-size: 12px;
	}
	.older-button {
		cursor: pointer;
	}
	.topic-group {
		margin-bottom: 12px;
		border: 1px solid var(--wa-border);
		border-radius: 13px;
		background: color-mix(in srgb, var(--wa-surface) 94%, transparent);
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
		color: var(--wa-success);
		font-size: 12px;
		font-style: normal;
		text-transform: uppercase;
	}
	.topic-group strong {
		margin-top: 2px;
		font-size: 11px;
	}
	.topic-group p {
		margin: 3px 0 0;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.topic-messages {
		padding: 12px;
		border-top: 1px solid var(--wa-border-soft);
	}
	.template-gate {
		padding: 10px 12px;
		display: flex;
		align-items: center;
		gap: 9px;
		border-top: 1px solid var(--wa-border);
		background: var(--wa-surface-muted);
	}
	.template-gate {
		color: var(--wa-warning);
		background: var(--wa-warning-soft);
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
		font-size: 12px;
	}
	.template-gate span {
		margin-top: 2px;
		color: var(--wa-warning);
		font-size: 12px;
	}
	.dialog-form {
		width: min(480px, 80vw);
		display: grid;
		gap: 14px;
	}
	.folder-dialog-form {
		width: min(420px, 80vw);
	}
	.folder-dialog-icon {
		display: grid;
		place-items: center;
		width: 44px;
		height: 44px;
		border-radius: 13px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
	}
	.folder-dialog-form input[type='color'] {
		width: 100%;
		height: 42px;
		padding: 4px;
		border: 1px solid var(--wa-border);
		border-radius: 9px;
		background: var(--wa-surface-muted);
	}
	.dialog-form label {
		display: grid;
		gap: 6px;
		color: var(--wa-text);
		font-size: 12px;
		font-weight: 700;
	}
	.media-upload input[type='file'] {
		padding: 8px;
		border: 1px dashed var(--wa-border);
		border-radius: 8px;
		background: var(--wa-surface-muted);
	}
	.dialog-form :deep(.p-select),
	.dialog-form :deep(input) {
		width: 100%;
	}
	.message-info-grid {
		width: min(470px, 78vw);
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
	}
	.message-info-grid > div {
		min-width: 0;
		padding: 11px;
		border: 1px solid var(--wa-border-soft);
		border-radius: 9px;
		background: var(--wa-surface-muted);
	}
	.message-info-grid span,
	.message-info-grid strong {
		display: block;
	}
	.message-info-grid span {
		margin-bottom: 4px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.message-info-grid strong {
		overflow-wrap: anywhere;
		font-size: 13px;
	}
	.message-info-id {
		grid-column: 1 / -1;
	}
	@media (max-width: 1120px) {
		.inbox-workbench.context-open {
			grid-template-columns: var(--conversation-pane-width, 320px) 5px minmax(0, 1fr);
		}
		.inbox-workbench.context-open > :deep(.context-panel) {
			display: none;
		}
	}
	@media (max-width: 760px) {
		.inbox-page {
			height: calc(100dvh - 56px);
			padding: 0;
		}
		.inbox-workbench {
			grid-template-columns: 1fr;
		}
		.inbox-workbench > :deep(.resize-handle) {
			display: none;
		}
		.chat-panel {
			display: none;
		}
		.mobile-chat-open .list-panel {
			display: none;
		}
		.mobile-chat-open .chat-panel {
			display: flex;
			width: 100%;
			min-width: 0;
			animation: mobile-chat-in 170ms cubic-bezier(0.22, 1, 0.36, 1);
		}
		.template-gate {
			min-width: 0;
		}
		.template-gate {
			flex-wrap: wrap;
		}
		.template-gate :deep(.p-select) {
			width: 100%;
		}
		.dialog-form {
			width: 100%;
		}
		.message-info-grid {
			width: 100%;
			grid-template-columns: 1fr;
		}
		.message-info-id {
			grid-column: auto;
		}
	}
	@keyframes mobile-chat-in {
		from {
			opacity: 0;
			transform: translateX(12px);
		}
		to {
			opacity: 1;
			transform: translateX(0);
		}
	}
</style>
