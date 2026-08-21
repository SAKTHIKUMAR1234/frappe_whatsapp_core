<script setup>
	import { ref } from 'vue'
	import Button from 'primevue/button'
	import Textarea from 'primevue/textarea'
	import { MessageSquareText, Pencil, Send, Trash2 } from 'lucide-vue-next'
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
	})
	const emit = defineEmits(['created', 'updated', 'deleted', 'older'])
	const toast = useToast()
	const confirm = useConfirm()
	const draft = ref('')
	const saving = ref(false)
	const loadingOlder = ref(false)
	const editing = ref('')
	const editDraft = ref('')

	function canChange(comment) {
		return props.canManage || comment.user === props.currentUser
	}

	async function submit() {
		const content = draft.value.trim()
		if (!content || saving.value) return
		saving.value = true
		try {
			const row = await call('frappe_whatsapp_core.internal_comments.add_comment', {
				conversation: props.conversation,
				content,
			})
			draft.value = ''
			emit('created', row)
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

	function startEdit(comment) {
		editing.value = comment.name
		editDraft.value = comment.content || ''
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
	<section class="comments-panel">
		<header><MessageSquareText :size="15" /> Internal comments</header>
		<p class="private-copy">Visible only to team members. Nothing here is sent to WhatsApp.</p>
		<Button
			v-if="page?.has_more"
			label="Load older comments"
			text
			size="small"
			:loading="loadingOlder"
			@click="loadOlder"
		/>
		<div v-if="comments.length" class="comment-list">
			<article v-for="comment in comments" :key="comment.name" class="comment-card">
				<div class="comment-avatar">
					<img v-if="comment.user_image" :src="comment.user_image" alt="" />
					<template v-else>{{
						(comment.user_display_name || 'T').slice(0, 1).toUpperCase()
					}}</template>
				</div>
				<div class="comment-body">
					<header>
						<strong>{{ comment.user_display_name || 'Team member' }}</strong>
						<time>{{ formatDateTime(comment.creation) }}</time>
					</header>
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
				<div v-if="canChange(comment) && editing !== comment.name" class="comment-actions">
					<Button
						text
						rounded
						size="small"
						aria-label="Edit internal comment"
						@click="startEdit(comment)"
						><Pencil :size="13"
					/></Button>
					<Button
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
			<Textarea
				v-model="draft"
				rows="3"
				maxlength="2000"
				fluid
				placeholder="Add a private note for your team"
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
	.private-copy {
		margin: -4px 0 1px;
		color: var(--wa-muted);
		font-size: 11px;
		line-height: 1.45;
	}
	.comment-list {
		display: grid;
		gap: 9px;
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
		opacity: 0;
		transition: opacity 150ms ease;
	}
	.comment-card:hover .comment-actions,
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
