<script setup>
	import { computed, nextTick, onMounted, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import InputText from 'primevue/inputtext'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import Tag from 'primevue/tag'
	import {
		ArrowLeft,
		CheckCheck,
		LoaderCircle,
		MessageCircle,
		Search,
		Send,
	} from 'lucide-vue-next'
	import { useToast } from 'primevue/usetoast'
	import { call } from '@/services/frappe'

	const toast = useToast()
	const loading = ref(false)
	const loadingMessages = ref(false)
	const loadingOlder = ref(false)
	const conversations = ref([])
	const selected = ref(null)
	const messages = ref([])
	const teams = ref([])
	const search = ref('')
	const messageSearch = ref('')
	const statusFilter = ref('')
	const teamFilter = ref('')
	const draft = ref('')
	const hasOlder = ref(false)
	const nextBefore = ref(null)
	const messagePane = ref(null)
	const pending = ref([])
	const mobileChatOpen = ref(false)
	let searchTimer
	let messageSearchTimer

	const statuses = [
		{ label: 'All statuses', value: '' },
		{ label: 'Open', value: 'Open' },
		{ label: 'Pending', value: 'Pending' },
		{ label: 'Resolved', value: 'Resolved' },
	]
	const teamOptions = computed(() => [
		{ label: 'All teams', value: '' },
		...teams.value
			.filter((team) => team.enabled)
			.map((team) => ({ label: team.team_name, value: team.name })),
	])
	const assignmentUsers = computed(() => {
		const team = teams.value.find((entry) => entry.name === selected.value?.assigned_team)
		return [
			{ label: 'Unassigned', value: '' },
			...(team?.members || [])
				.filter((member) => member.enabled)
				.map((member) => ({ label: member.user, value: member.user })),
		]
	})
	const orderedMessages = computed(() => [...messages.value].reverse())

	function label(conversation) {
		return (
			conversation.display_value ||
			conversation.normalized_value ||
			conversation.conversation_key
		)
	}

	function initials(conversation) {
		return label(conversation)
			.split(/\s+/)
			.slice(0, 2)
			.map((part) => part[0])
			.join('')
			.toUpperCase()
	}

	function time(value) {
		if (!value) return ''
		return new Intl.DateTimeFormat(undefined, {
			day: '2-digit',
			month: 'short',
			hour: '2-digit',
			minute: '2-digit',
		}).format(new Date(value))
	}

	function showError(error, summary = 'Request failed') {
		toast.add({
			severity: 'error',
			summary,
			detail: error?.response?.data?.message || error?.message || 'Please try again.',
			life: 4500,
		})
	}

	async function loadConversations({ preserveSelection = true } = {}) {
		loading.value = true
		try {
			const result = await call('frappe_whatsapp_core.workspace_api.list_conversations', {
				search: search.value,
				status: statusFilter.value,
				team: teamFilter.value,
			})
			conversations.value = result.rows || []
			if (preserveSelection && selected.value) {
				selected.value =
					conversations.value.find((row) => row.name === selected.value.name) ||
					selected.value
			}
			if (!selected.value && conversations.value.length)
				await openConversation(conversations.value[0])
		} catch (error) {
			showError(error, 'Could not load conversations')
		} finally {
			loading.value = false
		}
	}

	async function openConversation(conversation) {
		selected.value = conversation
		mobileChatOpen.value = true
		messageSearch.value = ''
		pending.value = []
		await loadMessages()
		await call('frappe_whatsapp_core.workspace_api.mark_read', {
			conversation: conversation.name,
		})
		conversation.unread_count = 0
	}

	async function loadMessages({ older = false } = {}) {
		if (!selected.value) return
		if (older) loadingOlder.value = true
		else loadingMessages.value = true
		try {
			const result = await call('frappe_whatsapp_core.workspace_api.list_messages', {
				conversation: selected.value.name,
				before: older ? nextBefore.value : '',
				search: messageSearch.value,
				limit: 50,
			})
			messages.value = older
				? [...messages.value, ...(result.rows || [])]
				: result.rows || []
			hasOlder.value = result.has_more
			nextBefore.value = result.next_before
			if (!older) await scrollToBottom()
		} catch (error) {
			showError(error, 'Could not load messages')
		} finally {
			loadingMessages.value = false
			loadingOlder.value = false
		}
	}

	async function scrollToBottom() {
		await nextTick()
		if (messagePane.value) messagePane.value.scrollTop = messagePane.value.scrollHeight
	}

	function sendMessage() {
		const body = draft.value.trim()
		if (!body || !selected.value) return
		const conversationName = selected.value.name
		const local = {
			name: `pending-${Date.now()}-${Math.random()}`,
			body,
			direction: 'Outbound',
			provider_timestamp: new Date().toISOString(),
			delivery_status: 'Queued',
		}
		draft.value = ''
		pending.value.push(local)
		scrollToBottom()
		call('frappe_whatsapp_core.workspace_api.send_text', {
			conversation: conversationName,
			body,
		})
			.then(async () => {
				pending.value = pending.value.filter((item) => item.name !== local.name)
				if (selected.value?.name === conversationName) await loadMessages()
				loadConversations()
			})
			.catch((error) => {
				local.delivery_status = 'Failed'
				showError(error, 'Message was not queued')
			})
	}

	async function updateAssignment(field, value) {
		if (!selected.value) return
		const payload = { conversation: selected.value.name, [field]: value || '' }
		if (field === 'team') payload.user = ''
		try {
			selected.value = await call(
				'frappe_whatsapp_core.workspace_api.assign_conversation',
				payload,
			)
			await loadConversations()
		} catch (error) {
			showError(error, 'Could not update conversation')
		}
	}

	watch(search, () => {
		clearTimeout(searchTimer)
		searchTimer = setTimeout(() => loadConversations({ preserveSelection: false }), 300)
	})
	watch([statusFilter, teamFilter], () => loadConversations({ preserveSelection: false }))
	watch(messageSearch, () => {
		clearTimeout(messageSearchTimer)
		messageSearchTimer = setTimeout(loadMessages, 300)
	})

	onMounted(async () => {
		teams.value = await call('frappe_whatsapp_core.workspace_api.list_teams')
		await loadConversations()
	})
</script>

<template>
	<div class="conversation-page surface-card">
		<aside class="conversation-list">
			<header>
				<div>
					<span class="eyebrow">Team inbox</span>
					<h1>Conversations</h1>
				</div>
				<Tag :value="`${conversations.length} visible`" severity="secondary" rounded />
			</header>
			<div class="search-field">
				<Search :size="16" />
				<input v-model="search" placeholder="Search people or messages" />
			</div>
			<div class="filters">
				<Select
					v-model="statusFilter"
					:options="statuses"
					option-label="label"
					option-value="value"
				/>
				<Select
					v-model="teamFilter"
					:options="teamOptions"
					option-label="label"
					option-value="value"
				/>
			</div>
			<div class="conversation-scroll">
				<div v-if="loading" class="state">
					<LoaderCircle class="spin" :size="22" />Loading inbox…
				</div>
				<button
					v-for="conversation in conversations"
					v-else
					:key="conversation.name"
					:class="['conversation-row', { active: selected?.name === conversation.name }]"
					@click="openConversation(conversation)"
				>
					<span class="avatar">{{ initials(conversation) }}</span>
					<span class="conversation-copy">
						<strong>{{ label(conversation) }}</strong>
						<small>{{ conversation.last_message_body || 'No messages yet' }}</small>
					</span>
					<span class="conversation-meta">
						<time>{{ time(conversation.last_message_at) }}</time>
						<em v-if="conversation.unread_count">{{ conversation.unread_count }}</em>
					</span>
				</button>
				<div v-if="!loading && !conversations.length" class="state">
					<MessageCircle :size="25" />No matching conversations
				</div>
			</div>
		</aside>

		<section v-if="selected" :class="['chat-panel', { 'mobile-open': mobileChatOpen }]">
			<header class="chat-header">
				<div class="chat-person">
					<Button
						class="mobile-back"
						text
						rounded
						aria-label="Back to conversations"
						@click="mobileChatOpen = false"
					>
						<ArrowLeft :size="19" />
					</Button>
					<span class="avatar">{{ initials(selected) }}</span>
					<div>
						<strong>{{ label(selected) }}</strong>
						<small>{{ selected.normalized_value }}</small>
					</div>
				</div>
				<div class="assignment">
					<Select
						:model-value="selected.assigned_team || ''"
						:options="teamOptions"
						option-label="label"
						option-value="value"
						placeholder="Assign team"
						@update:model-value="updateAssignment('team', $event)"
					/>
					<Select
						:model-value="selected.assigned_user || ''"
						:options="assignmentUsers"
						option-label="label"
						option-value="value"
						placeholder="Assign user"
						@update:model-value="updateAssignment('user', $event)"
					/>
					<Select
						:model-value="selected.status"
						:options="statuses.slice(1)"
						option-label="label"
						option-value="value"
						@update:model-value="updateAssignment('status', $event)"
					/>
				</div>
			</header>
			<div class="message-search">
				<Search :size="14" /><InputText
					v-model="messageSearch"
					placeholder="Search this chat"
				/>
			</div>
			<div ref="messagePane" class="messages">
				<Button
					v-if="hasOlder"
					:loading="loadingOlder"
					label="Load earlier messages"
					text
					size="small"
					@click="loadMessages({ older: true })"
				/>
				<div v-if="loadingMessages" class="state">
					<LoaderCircle class="spin" :size="22" />Loading messages…
				</div>
				<article
					v-for="message in [...orderedMessages, ...pending]"
					v-else
					:key="message.name"
					:class="['bubble', message.direction === 'Outbound' ? 'outbound' : 'inbound']"
				>
					<p>{{ message.body || `[${message.message_type}]` }}</p>
					<footer>
						{{ time(message.provider_timestamp || message.creation) }}
						<CheckCheck v-if="message.direction === 'Outbound'" :size="13" />
						<span v-if="message.delivery_status === 'Failed'" class="failed"
							>Failed</span
						>
					</footer>
				</article>
			</div>
			<form class="composer" @submit.prevent="sendMessage">
				<Textarea
					v-model="draft"
					auto-resize
					rows="1"
					placeholder="Write a message…"
					@keydown.enter.exact.prevent="sendMessage"
				/>
				<Button type="submit" rounded :disabled="!draft.trim()" aria-label="Send">
					<Send :size="18" />
				</Button>
			</form>
		</section>
		<section v-else class="empty-chat">
			<MessageCircle :size="42" />
			<h2>Select a conversation</h2>
			<p>Messages, assignments and delivery state will appear here.</p>
		</section>
	</div>
</template>

<style scoped>
	.conversation-page {
		height: calc(100vh - 124px);
		min-height: 570px;
		display: grid;
		grid-template-columns: 350px 1fr;
		overflow: hidden;
	}
	.conversation-list {
		min-width: 0;
		display: flex;
		flex-direction: column;
		border-right: 1px solid var(--wa-border);
	}
	.conversation-list > header,
	.chat-header {
		min-height: 74px;
		padding: 15px 17px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		border-bottom: 1px solid var(--wa-border);
	}
	h1 {
		margin: 3px 0 0;
		font-size: 20px;
	}
	.search-field {
		margin: 13px 13px 8px;
		padding: 9px 11px;
		display: flex;
		gap: 8px;
		align-items: center;
		border: 1px solid var(--wa-border);
		border-radius: 10px;
		color: #829088;
	}
	.search-field input {
		width: 100%;
		border: 0;
		outline: 0;
		background: transparent;
		font-size: 11px;
	}
	.filters {
		padding: 0 13px 11px;
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 7px;
	}
	.filters :deep(.p-select),
	.assignment :deep(.p-select) {
		min-width: 0;
		font-size: 10px;
	}
	.conversation-scroll {
		min-height: 0;
		overflow-y: auto;
	}
	.conversation-row {
		width: 100%;
		display: grid;
		grid-template-columns: 42px minmax(0, 1fr) auto;
		gap: 10px;
		align-items: center;
		padding: 12px 14px;
		border: 0;
		border-bottom: 1px solid #edf1ef;
		background: white;
		text-align: left;
		cursor: pointer;
	}
	.conversation-row:hover,
	.conversation-row.active {
		background: #effaf6;
	}
	.avatar {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		flex: none;
		border-radius: 50%;
		color: #075e54;
		background: #d9f8eb;
		font-size: 11px;
		font-weight: 800;
	}
	.conversation-copy,
	.conversation-copy strong,
	.conversation-copy small {
		min-width: 0;
		display: block;
	}
	.conversation-copy strong {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 11px;
	}
	.conversation-copy small {
		margin-top: 4px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: #7c8983;
		font-size: 9px;
	}
	.conversation-meta {
		align-self: stretch;
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		justify-content: space-between;
	}
	.conversation-meta time {
		color: #929d98;
		font-size: 8px;
	}
	.conversation-meta em {
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		display: grid;
		place-items: center;
		border-radius: 10px;
		color: white;
		background: #18a879;
		font-size: 8px;
		font-style: normal;
	}
	.chat-panel {
		min-width: 0;
		display: flex;
		flex-direction: column;
		background: #f3f6f4;
	}
	.chat-header {
		background: white;
	}
	.chat-person {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.mobile-back {
		display: none;
	}
	.chat-person strong,
	.chat-person small {
		display: block;
	}
	.chat-person strong {
		font-size: 12px;
	}
	.chat-person small {
		margin-top: 3px;
		color: #839088;
		font-size: 9px;
	}
	.assignment {
		max-width: 570px;
		display: grid;
		grid-template-columns: repeat(3, minmax(115px, 1fr));
		gap: 7px;
	}
	.message-search {
		padding: 7px 14px;
		display: flex;
		align-items: center;
		gap: 7px;
		border-bottom: 1px solid var(--wa-border);
		color: #7f8d86;
		background: #fafcfb;
	}
	.message-search :deep(input) {
		width: 250px;
		padding: 5px 7px;
		border: 0;
		box-shadow: none;
		background: transparent;
		font-size: 10px;
	}
	.messages {
		min-height: 0;
		flex: 1;
		padding: 20px clamp(15px, 5vw, 70px);
		display: flex;
		flex-direction: column;
		gap: 7px;
		overflow-y: auto;
	}
	.bubble {
		max-width: min(72%, 620px);
		padding: 9px 11px 6px;
		border-radius: 12px;
		box-shadow: 0 1px 2px #11251e13;
	}
	.bubble.inbound {
		align-self: flex-start;
		border-bottom-left-radius: 3px;
		background: white;
	}
	.bubble.outbound {
		align-self: flex-end;
		border-bottom-right-radius: 3px;
		background: #d9f8e9;
	}
	.bubble p {
		margin: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font-size: 12px;
		line-height: 1.45;
	}
	.bubble footer {
		margin-top: 4px;
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 4px;
		color: #718078;
		font-size: 8px;
	}
	.failed {
		color: #b42318;
		font-weight: 700;
	}
	.composer {
		padding: 11px 14px;
		display: flex;
		align-items: flex-end;
		gap: 9px;
		border-top: 1px solid var(--wa-border);
		background: white;
	}
	.composer :deep(textarea) {
		max-height: 120px;
		flex: 1;
		resize: none;
		font-size: 12px;
	}
	.state,
	.empty-chat {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 8px;
		color: #829088;
		font-size: 10px;
	}
	.state {
		min-height: 130px;
	}
	.empty-chat {
		background: #f5f8f6;
	}
	.empty-chat h2 {
		margin: 8px 0 0;
		color: #28372f;
	}
	.empty-chat p {
		margin: 0;
	}
	.spin {
		animation: spin 0.9s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (max-width: 960px) {
		.conversation-page {
			grid-template-columns: 300px 1fr;
		}
		.assignment {
			grid-template-columns: 1fr;
		}
		.chat-header {
			align-items: flex-start;
			gap: 8px;
		}
	}
	@media (max-width: 700px) {
		.conversation-page {
			height: calc(100vh - 98px);
			display: block;
		}
		.conversation-list {
			height: 100%;
			border-right: 0;
		}
		.chat-panel {
			display: none;
			position: absolute;
			inset: 0;
			z-index: 5;
		}
		.chat-panel.mobile-open {
			display: flex;
		}
		.mobile-back {
			display: inline-flex;
		}
		.bubble {
			max-width: 88%;
		}
	}
</style>
