<script setup>
	import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import Select from 'primevue/select'
	import Textarea from 'primevue/textarea'
	import MultiLinkField from '@/components/form/MultiLinkField.vue'
	import {
		CheckCircle2,
		MessageSquareText,
		Pencil,
		RotateCcw,
		Reply,
		Send,
		Trash2,
		X,
	} from 'lucide-vue-next'
	import { useConfirm } from 'primevue/useconfirm'
	import { useToast } from 'primevue/usetoast'
	import { call, errorMessage } from '@/services/frappe'
	import { formatDateTime } from '@/utils/datetime'

	const props = defineProps({
		conversation: { type: String, required: true },
		comments: { type: Array, default: () => [] },
		page: { type: Object, default: () => ({ has_more: false }) },
		currentUser: { type: String, default: '' },
		canManage: { type: Boolean, default: false },
		draftMessages: { type: Array, default: () => [] },
		draftReference: { type: Object, default: null },
		focusComment: { type: String, default: '' },
	})
	const emit = defineEmits([
		'created',
		'updated',
		'deleted',
		'older',
		'draft-consumed',
		'open-message',
	])
	const toast = useToast()
	const confirm = useConfirm()
	const draft = ref('')
	const saving = ref(false)
	const loadingOlder = ref(false)
	const editing = ref('')
	const editDraft = ref('')
	const assignees = ref([])
	const assignedTo = ref('')
	const mentionedUsers = ref([])
	const replyingTo = ref(null)
	const commentList = ref(null)
	let restoredConversation = ''
	let rememberTimer = null

	function positionKey(conversation = props.conversation) {
		return `whatsapp-core:internal-comments:${conversation}:last-read`
	}

	async function restoreCommentPosition() {
		await nextTick()
		const list = commentList.value
		if (!list || !props.comments.length) return
		const stored = localStorage.getItem(positionKey())
		const cards = [...list.querySelectorAll('[data-comment-name]')]
		const target = cards.find((card) => card.dataset.commentName === stored) || cards.at(-1)
		if (!target) return
		list.scrollTop = Math.max(0, target.offsetTop)
		localStorage.setItem(positionKey(), target.dataset.commentName)
		restoredConversation = props.conversation
	}

	function rememberCommentPosition() {
		window.clearTimeout(rememberTimer)
		rememberTimer = window.setTimeout(() => {
			const list = commentList.value
			if (!list) return
			const bounds = list.getBoundingClientRect()
			const visible = [...list.querySelectorAll('[data-comment-name]')].filter((card) => {
				const cardBounds = card.getBoundingClientRect()
				return cardBounds.bottom > bounds.top && cardBounds.top < bounds.bottom
			})
			const last = visible.at(-1)
			if (last?.dataset.commentName)
				localStorage.setItem(positionKey(), last.dataset.commentName)
		}, 120)
	}

	function canChange(comment) {
		return (
			props.canManage ||
			comment.user === props.currentUser ||
			comment.assigned_to === props.currentUser
		)
	}

	async function submit() {
		const content = draft.value.trim()
		if (!content || saving.value) return
		saving.value = true
		try {
			const row = await call('frappe_whatsapp_core.internal_comments.add_comment', {
				conversation: props.conversation,
				content,
				assigned_to: assignedTo.value,
				mentioned_users: mentionedUsers.value,
				parent_comment: replyingTo.value?.name || '',
				reference_doctype: props.draftReference?.doctype || '',
				reference_name: props.draftReference?.name || '',
				message_references: props.draftMessages.map((message) => message.name),
			})
			draft.value = ''
			assignedTo.value = ''
			mentionedUsers.value = []
			replyingTo.value = null
			emit('created', row)
			emit('draft-consumed')
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Comment was not saved',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			saving.value = false
		}
	}

	async function setStatus(comment, status) {
		if (saving.value) return
		saving.value = true
		try {
			const row = await call('frappe_whatsapp_core.internal_comments.update_comment', {
				comment: comment.name,
				status,
			})
			emit('updated', row)
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Task status was not updated',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			saving.value = false
		}
	}

	watch(
		() => props.conversation,
		async (conversation) => {
			restoredConversation = ''
			assignees.value = conversation
				? await call('frappe_whatsapp_core.internal_comments.work_item_assignees', {
						conversation,
					}).catch(() => [])
				: []
		},
		{ immediate: true },
	)
	watch(
		() => [props.conversation, props.comments.map((comment) => comment.name).join('|')],
		() => {
			if (props.conversation && restoredConversation !== props.conversation)
				void restoreCommentPosition()
		},
		{ immediate: true, flush: 'post' },
	)
	onBeforeUnmount(() => window.clearTimeout(rememberTimer))

	function startEdit(comment) {
		editing.value = comment.name
		editDraft.value = comment.content || ''
	}

	function startReply(comment) {
		replyingTo.value = comment
		requestAnimationFrame(() =>
			document
				.querySelector('textarea[name="internal_note"]')
				?.focus({ preventScroll: true }),
		)
	}

	async function saveEdit(comment) {
		const content = editDraft.value.trim()
		if (!content || saving.value) return
		saving.value = true
		try {
			const row = await call('frappe_whatsapp_core.internal_comments.update_comment', {
				comment: comment.name,
				content,
			})
			editing.value = ''
			emit('updated', row)
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Comment was not updated',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			saving.value = false
		}
	}

	function requestDelete(comment) {
		confirm.require({
			header: 'Delete internal comment?',
			message:
				'This removes the note for every team member. It does not affect the WhatsApp chat.',
			rejectLabel: 'Keep comment',
			acceptLabel: 'Delete',
			acceptClass: 'p-button-danger',
			accept: () => remove(comment),
		})
	}

	async function remove(comment) {
		try {
			await call('frappe_whatsapp_core.internal_comments.delete_comment', {
				comment: comment.name,
			})
			emit('deleted', comment.name)
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Comment was not deleted',
				detail: errorMessage(error),
				life: 4500,
			})
		}
	}

	async function loadOlder() {
		if (!props.page?.has_more || loadingOlder.value) return
		loadingOlder.value = true
		try {
			const result = await call('frappe_whatsapp_core.internal_comments.comment_page', {
				conversation: props.conversation,
				before: props.page.next_before,
				before_name: props.page.next_before_name,
				limit: 30,
			})
			emit('older', result)
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Older comments could not be loaded',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			loadingOlder.value = false
		}
	}
</script>

<template>
	<section class="comments-panel" data-internal-work>
		<header title="Visible only to your team">
			<MessageSquareText :size="15" /> Internal notes
		</header>
		<Button
			v-if="page?.has_more"
			label="Load older comments"
			text
			size="small"
			:loading="loadingOlder"
			@click="loadOlder"
		/>
		<div
			v-if="comments.length"
			ref="commentList"
			class="comment-list"
			tabindex="0"
			aria-label="Internal notes"
			@scroll.passive="rememberCommentPosition"
		>
			<article
				v-for="comment in comments"
				:key="comment.name"
				:class="['comment-card', { focused: focusComment === comment.name }]"
				:data-comment-name="comment.name"
			>
				<div class="comment-avatar">
					<img
						v-if="comment.user_image"
						:src="comment.user_image"
						alt=""
						width="28"
						height="28"
						loading="lazy"
					/>
					<template v-else>{{
						(comment.user_display_name || 'T').slice(0, 1).toUpperCase()
					}}</template>
				</div>
				<div class="comment-body">
					<div v-if="comment.parent_comment" class="reply-reference">
						<Reply :size="11" />
						<span>{{ comment.parent_user_display_name || 'Team member' }}</span>
						<em>{{ comment.parent_content }}</em>
					</div>
					<header>
						<strong>{{ comment.user_display_name || 'Team member' }}</strong>
						<time>{{ formatDateTime(comment.creation) }}</time>
					</header>
					<div class="work-meta">
						<span :class="['work-status', comment.status?.toLowerCase()]">
							{{ comment.status || 'Open' }}
						</span>
						<span v-if="comment.assigned_to">
							Assigned to {{ comment.assigned_to_display_name || 'team member' }}
						</span>
						<span v-if="comment.message_references?.length">
							{{ comment.message_references.length }} referenced
							{{ comment.message_references.length === 1 ? 'message' : 'messages' }}
						</span>
						<span v-if="comment.reference_label">{{ comment.reference_label }}</span>
					</div>
					<div v-if="comment.mentioned_user_details?.length" class="mention-row">
						<span v-for="user in comment.mentioned_user_details" :key="user.name">
							@{{ user.label }}
						</span>
					</div>
					<div v-if="comment.message_reference_details?.length" class="message-links">
						<Button
							v-for="message in comment.message_reference_details"
							:key="message.name"
							text
							size="small"
							:label="message.body || message.message_type || 'Referenced message'"
							@click="$emit('open-message', message.name)"
						/>
					</div>
					<template v-if="editing === comment.name">
						<Textarea v-model="editDraft" rows="3" maxlength="2000" fluid />
						<div class="edit-actions">
							<Button label="Cancel" text size="small" @click="editing = ''" />
							<Button
								label="Save"
								size="small"
								:loading="saving"
								@click="saveEdit(comment)"
							/>
						</div>
					</template>
					<p v-else>{{ comment.content }}</p>
				</div>
				<div v-if="editing !== comment.name" class="comment-actions">
					<Button
						text
						rounded
						size="small"
						aria-label="Reply to internal comment"
						@click="startReply(comment)"
						><Reply :size="13"
					/></Button>
					<Button
						v-if="canChange(comment)"
						text
						rounded
						size="small"
						:aria-label="
							comment.status === 'Resolved' ? 'Reopen task' : 'Resolve task'
						"
						@click="
							setStatus(comment, comment.status === 'Resolved' ? 'Open' : 'Resolved')
						"
					>
						<RotateCcw v-if="comment.status === 'Resolved'" :size="13" />
						<CheckCircle2 v-else :size="13" />
					</Button>
					<Button
						v-if="canChange(comment)"
						text
						rounded
						size="small"
						aria-label="Edit internal comment"
						@click="startEdit(comment)"
						><Pencil :size="13"
					/></Button>
					<Button
						v-if="canChange(comment)"
						text
						rounded
						size="small"
						severity="danger"
						aria-label="Delete internal comment"
						@click="requestDelete(comment)"
						><Trash2 :size="13"
					/></Button>
				</div>
			</article>
		</div>
		<p v-else class="empty-copy">No internal comments yet.</p>
		<div class="comment-composer">
			<div v-if="replyingTo" class="composer-reference">
				<Reply :size="13" />
				<span>
					Replying to
					<strong>{{ replyingTo.user_display_name || 'team member' }}</strong>
				</span>
				<Button text rounded aria-label="Cancel reply" @click="replyingTo = null">
					<X :size="13" />
				</Button>
			</div>
			<div v-if="draftReference" class="composer-reference">
				<MessageSquareText :size="13" />
				<span
					>Linked to <strong>{{ draftReference.label || 'summary' }}</strong></span
				>
				<Button
					text
					rounded
					aria-label="Remove summary link"
					@click="$emit('draft-consumed')"
				>
					<X :size="13" />
				</Button>
			</div>
			<div v-if="draftMessages.length" class="referenced-messages">
				<strong>{{ draftMessages.length }} messages selected</strong>
				<ul>
					<li v-for="message in draftMessages.slice(0, 3)" :key="message.name">
						{{ message.body || message.message_type || 'Message' }}
					</li>
				</ul>
				<Button label="Clear" text size="small" @click="$emit('draft-consumed')" />
			</div>
			<Select
				v-model="assignedTo"
				:options="assignees"
				option-label="label"
				option-value="name"
				show-clear
				filter
				placeholder="Assign to a team member"
				aria-label="Assign internal task"
			/>
			<MultiLinkField
				v-model="mentionedUsers"
				:options="assignees"
				option-label="label"
				option-value="name"
				:max-selected-labels="3"
				placeholder="Mention team members"
				aria-label="Mention team members"
			/>
			<Textarea
				v-model="draft"
				rows="3"
				maxlength="2000"
				fluid
				name="internal_note"
				aria-label="Internal note"
				placeholder="Add a private note for your team…"
				@keydown.meta.enter.prevent="submit"
				@keydown.ctrl.enter.prevent="submit"
			/>
			<Button
				:disabled="!draft.trim()"
				:loading="saving"
				aria-label="Add internal comment"
				@click="submit"
				><Send :size="15"
			/></Button>
		</div>
	</section>
</template>

<style scoped>
	.comments-panel {
		display: grid;
		gap: 11px;
	}
	.comments-panel > header {
		margin-bottom: 0;
	}
	.comment-list {
		display: grid;
		gap: 9px;
		max-height: min(42vh, 420px);
		padding-right: 3px;
		overflow-y: auto;
		scrollbar-gutter: stable;
	}
	.comment-card {
		position: relative;
		display: grid;
		grid-template-columns: 28px minmax(0, 1fr) auto;
		gap: 8px;
		padding: 10px;
		border: 1px solid var(--wa-border-soft);
		border-radius: 11px;
		background: var(--wa-surface-muted);
	}
	.comment-card.focused {
		border-color: var(--wa-primary);
		box-shadow: 0 0 0 2px var(--wa-primary-soft);
	}
	.comment-avatar {
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		overflow: hidden;
		border-radius: 50%;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		font-size: 10px;
		font-weight: 800;
	}
	.comment-avatar img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.comment-body {
		min-width: 0;
	}
	.comment-body > header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 7px;
	}
	.comment-body strong {
		overflow: hidden;
		color: var(--wa-text);
		font-size: 11px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.comment-body time {
		flex: 0 0 auto;
		color: var(--wa-muted);
		font-size: 9px;
	}
	.comment-body p {
		margin: 5px 0 0;
		color: var(--wa-text);
		font-size: 12px;
		line-height: 1.5;
		overflow-wrap: anywhere;
		white-space: pre-wrap;
	}
	.comment-actions {
		display: flex;
		align-self: start;
		opacity: 0.62;
		transition: opacity 150ms ease;
	}
	.comment-card:hover .comment-actions,
	.comment-card:focus-within .comment-actions,
	.comment-actions:focus-within {
		opacity: 1;
	}
	.comment-actions :deep(.p-button) {
		width: 26px;
		height: 26px;
		padding: 0;
	}
	.comment-composer {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 7px;
		align-items: end;
	}
	.comment-composer > :deep(.p-select),
	.comment-composer > :deep(.p-multiselect),
	.composer-reference,
	.referenced-messages {
		grid-column: 1 / -1;
	}
	.composer-reference,
	.reply-reference {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		padding: 7px 8px;
		border-left: 2px solid var(--wa-primary);
		border-radius: 6px;
		color: var(--wa-muted);
		background: var(--wa-primary-soft);
		font-size: 10px;
	}
	.composer-reference > span,
	.reply-reference em {
		min-width: 0;
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.reply-reference {
		margin-bottom: 6px;
		padding: 5px 7px;
	}
	.reply-reference em {
		font-style: normal;
	}
	.mention-row {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 6px;
	}
	.mention-row span {
		padding: 2px 6px;
		border-radius: 999px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		font-size: 9px;
		font-weight: 700;
	}
	.message-links {
		display: grid;
		gap: 3px;
		margin-top: 6px;
	}
	.message-links :deep(.p-button) {
		min-width: 0;
		justify-content: flex-start;
		padding: 4px 6px;
	}
	.message-links :deep(.p-button-label) {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-align: left;
	}
	.referenced-messages {
		padding: 9px;
		border: 1px solid var(--wa-primary);
		border-radius: 9px;
		background: var(--wa-primary-soft);
		font-size: 11px;
	}
	.referenced-messages ul {
		margin: 5px 0 0;
		padding-left: 18px;
		color: var(--wa-muted);
	}
	.referenced-messages li {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.work-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		margin-top: 4px;
		color: var(--wa-muted);
		font-size: 10px;
	}
	.work-status {
		padding: 1px 5px;
		border-radius: 999px;
		color: var(--wa-warning, #b45309);
		background: color-mix(in srgb, currentColor 12%, transparent);
	}
	.work-status.resolved {
		color: var(--wa-success);
	}
	.comment-composer :deep(textarea) {
		resize: vertical;
		min-height: 66px;
		font-size: 12px;
	}
	.comment-composer :deep(.p-button) {
		width: 34px;
		height: 34px;
		padding: 0;
	}
	.edit-actions {
		display: flex;
		justify-content: flex-end;
		gap: 4px;
		margin-top: 5px;
	}
	@media (hover: none) {
		.comment-actions {
			opacity: 1;
		}
	}
</style>
