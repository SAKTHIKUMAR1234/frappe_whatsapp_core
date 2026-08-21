<script setup>
	import { computed, ref } from 'vue'
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import {
		Bot,
		Folder,
		ImagePlus,
		RefreshCw,
		Star,
		UsersRound,
		UserRoundCheck,
	} from 'lucide-vue-next'
	import Button from 'primevue/button'
	import { useToast } from 'primevue/usetoast'
	import { call, errorMessage, uploadFile } from '@/services/frappe'

	const props = defineProps({
		data: { type: Object, required: true },
		canManage: { type: Boolean, default: false },
		folders: { type: Array, default: () => [] },
	})

	const emit = defineEmits(['status', 'refresh-summary', 'avatar-changed', 'folder'])
	const toast = useToast()
	const avatarUploading = ref(false)
	const teams = computed(() => {
		const values = [props.data.assigned_team_details, ...(props.data.contact_teams || [])]
		return [...new Map(values.filter(Boolean).map((team) => [team.name, team])).values()]
	})

	const statusOptions = ['Open', 'Pending', 'Resolved']
	const selectedFolders = computed(
		() => new Set((props.data.contact_folders || []).map((folder) => folder.name)),
	)
	const readerCoverage = computed(() => {
		const expected = new Set((props.data.expected_readers || []).map((reader) => reader.user))
		return (props.data.readers || []).filter((reader) => expected.has(reader.user)).length
	})

	async function selectAvatar(event) {
		const file = event.target.files?.[0]
		if (!file) return
		avatarUploading.value = true
		try {
			const stored = await uploadFile(file, true)
			await call('frappe_whatsapp_core.workspace_api.update_contact_avatar', {
				identity: props.data.identity?.name,
				avatar: stored.file_url,
			})
			emit('avatar-changed')
			toast.add({ severity: 'success', summary: 'Contact image updated', life: 2500 })
		} catch (error) {
			toast.add({
				severity: 'error',
				summary: 'Image update failed',
				detail: errorMessage(error),
				life: 4500,
			})
		} finally {
			avatarUploading.value = false
			event.target.value = ''
		}
	}
</script>

<template>
	<aside class="context-panel">
		<section>
			<div class="eyebrow">Conversation</div>
			<div class="identity">
				<span>
					<img
						v-if="data.contact_presentation?.avatar"
						:src="data.contact_presentation.avatar"
						alt="Contact image"
					/>
					<template v-else>{{
						(data.display_name || 'WA').slice(0, 2).toUpperCase()
					}}</template>
				</span>
				<div>
					<strong>{{ data.display_name }}</strong>
					<small v-if="data.contact_presentation?.secondary_text">
						{{ data.contact_presentation.secondary_text }}
					</small>
				</div>
			</div>
			<label v-if="canManage" for="contact-avatar" class="avatar-upload">
				<ImagePlus :size="14" />
				{{ avatarUploading ? 'Uploading…' : 'Upload contact image' }}
			</label>
			<input
				v-if="canManage"
				id="contact-avatar"
				class="avatar-input"
				type="file"
				accept="image/png,image/jpeg,image/webp,image/gif"
				:disabled="avatarUploading"
				@change="selectAvatar"
			/>
			<Select
				v-if="canManage"
				:model-value="data.conversation?.status"
				:options="statusOptions"
				class="status-select"
				@update:model-value="$emit('status', $event)"
			/>
			<span v-else class="status-readonly">{{ data.conversation?.status }}</span>
		</section>

		<section>
			<header><UsersRound :size="15" /> Teams</header>
			<div class="team-list">
				<span v-for="team in teams" :key="team.name" class="team-tag">
					<img v-if="team.avatar_url" :src="team.avatar_url" alt="" />
					<UsersRound v-else :size="13" />
					{{ team.team_name }}
				</span>
				<span v-if="!teams.length" class="empty-copy">Unassigned contact</span>
			</div>
		</section>

		<section>
			<header><UserRoundCheck :size="15" /> Read by</header>
			<div v-if="data.expected_readers?.length" class="coverage-copy">
				<strong>{{ readerCoverage }} / {{ data.expected_readers.length }}</strong>
				<span>team members have opened this conversation</span>
			</div>
			<div class="reader-list">
				<Tag
					v-for="reader in data.readers"
					:key="reader.user"
					:value="reader.display_name || reader.full_name || 'Team member'"
					severity="secondary"
					rounded
				/>
				<span v-if="!data.readers?.length" class="empty-copy"
					>Not read by the team yet.</span
				>
			</div>
		</section>

		<section>
			<header><Folder :size="15" /> My folders</header>
			<div class="folder-list">
				<Button
					v-for="folder in folders"
					:key="folder.name"
					unstyled
					:class="['folder-tag', { active: selectedFolders.has(folder.name) }]"
					:aria-pressed="selectedFolders.has(folder.name)"
					@click="
						$emit('folder', { folder, enabled: !selectedFolders.has(folder.name) })
					"
				>
					<Star v-if="folder.folder_type === 'Important'" :size="13" />
					<Folder v-else :size="13" />
					{{ folder.folder_name }}
				</Button>
				<span v-if="!folders.length" class="empty-copy">No personal folders yet.</span>
			</div>
		</section>

		<section class="ai-note">
			<header>
				<span><Bot :size="15" /> Contact summary</span>
				<Button
					v-if="canManage"
					text
					rounded
					aria-label="Refresh contact summary"
					@click="$emit('refresh-summary')"
				>
					<RefreshCw :size="14" />
				</Button>
			</header>
			<p v-if="data.contact_summary?.summary">{{ data.contact_summary.summary }}</p>
			<p v-else>No summary has been generated for this contact yet.</p>
			<div v-if="data.contact_summary?.categories?.length" class="summary-tags">
				<Tag
					v-for="category in data.contact_summary.categories"
					:key="category"
					:value="category"
					severity="info"
					rounded
				/>
			</div>
			<ul v-if="data.contact_summary?.action_items?.length" class="summary-actions">
				<li v-for="action in data.contact_summary.action_items" :key="action">
					{{ action }}
				</li>
			</ul>
		</section>
	</aside>
</template>

<style scoped>
	.context-panel {
		min-height: 0;
		overflow-y: auto;
		border-left: 1px solid var(--wa-border);
		background: var(--wa-surface);
	}
	section {
		padding: 17px;
		border-bottom: 1px solid var(--wa-border-soft);
	}
	section > header {
		display: flex;
		align-items: center;
		gap: 7px;
		margin-bottom: 12px;
		color: var(--wa-muted);
		font-size: 11px;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.ai-note > header {
		justify-content: space-between;
	}
	.ai-note > header > span {
		display: inline-flex;
		align-items: center;
		gap: 7px;
	}
	.identity {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 11px 0 13px;
	}
	.identity > span {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border-radius: 12px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
		font-size: 12px;
		font-weight: 800;
	}
	.identity > span img {
		width: 100%;
		height: 100%;
		border-radius: inherit;
		object-fit: cover;
	}
	.avatar-upload {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin: -3px 0 12px;
		color: var(--wa-primary);
		font-size: 11px;
		font-weight: 750;
		cursor: pointer;
	}
	.avatar-input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
		pointer-events: none;
	}
	.identity strong,
	.identity small {
		display: block;
	}
	.identity strong {
		font-size: 13px;
	}
	.identity small {
		margin-top: 3px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.status-select {
		width: 100%;
	}
	.status-readonly {
		display: inline-flex;
		padding: 5px 9px;
		border-radius: 999px;
		background: var(--wa-surface-muted);
		color: var(--wa-muted);
		font-size: 12px;
		font-weight: 700;
	}
	.reader-list {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.coverage-copy {
		display: flex;
		align-items: baseline;
		gap: 7px;
		margin-bottom: 9px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.coverage-copy strong {
		color: var(--wa-primary);
		font-size: 14px;
	}
	.folder-list {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.folder-tag {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 6px 9px;
		border: 1px solid var(--wa-border);
		border-radius: 999px;
		color: var(--wa-muted);
		background: var(--wa-surface-muted);
		font: inherit;
		font-size: 11px;
		font-weight: 700;
		cursor: pointer;
	}
	.folder-tag.active {
		border-color: var(--wa-primary);
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
	}
	.team-list {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.team-tag {
		max-width: 100%;
		padding: 5px 8px;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		border-radius: 999px;
		background: var(--wa-primary-soft);
		color: var(--wa-primary);
		font-size: 11px;
		font-weight: 700;
	}
	.team-tag img {
		width: 18px;
		height: 18px;
		border-radius: 50%;
		object-fit: cover;
	}
	.ai-note {
		background: var(--wa-primary-soft);
	}
	.ai-note p {
		margin: 0;
		color: var(--wa-muted);
		font-size: 12px;
		line-height: 1.55;
	}
	.summary-tags {
		display: flex;
		flex-wrap: wrap;
		gap: 5px;
		margin-top: 10px;
	}
	.summary-actions {
		margin: 10px 0 0;
		padding-left: 18px;
		color: var(--wa-text);
		font-size: 12px;
		line-height: 1.5;
	}
</style>
