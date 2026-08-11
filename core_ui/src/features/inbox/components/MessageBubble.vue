<script setup>
	import { computed, onBeforeUnmount } from 'vue'
	import {
		Check,
		CheckCheck,
		Clock3,
		CircleAlert,
		RefreshCw,
		Reply,
		MoreVertical,
	} from 'lucide-vue-next'
	import FlowResponseCard from '@/features/flows/components/FlowResponseCard.vue'
	import { flowReplyFromContent } from '@/features/flows/utils/flowResponse'

	const props = defineProps({
		message: { type: Object, required: true },
		messageIndex: { type: Map, default: () => new Map() },
		contactName: { type: String, default: 'Contact' },
		readers: { type: Array, default: () => [] },
	})
	const emit = defineEmits(['reply', 'retry', 'menu', 'quote'])
	let longPressTimer = null
	let longPressOrigin = null

	function openMenu(event) {
		event.preventDefault()
		event.stopPropagation()
		const rect = event.currentTarget?.getBoundingClientRect?.()
		emit('menu', {
			message: props.message,
			x: Number.isFinite(event.clientX) && event.clientX > 0 ? event.clientX : rect?.right,
			y: Number.isFinite(event.clientY) && event.clientY > 0 ? event.clientY : rect?.bottom,
		})
	}

	function startLongPress(event) {
		if (event.pointerType === 'mouse') return
		clearLongPress()
		longPressOrigin = { x: event.clientX, y: event.clientY }
		longPressTimer = window.setTimeout(() => openMenu(event), 480)
	}

	function trackLongPress(event) {
		if (!longPressOrigin) return
		if (
			Math.abs(event.clientX - longPressOrigin.x) > 8 ||
			Math.abs(event.clientY - longPressOrigin.y) > 8
		) {
			clearLongPress()
		}
	}

	function clearLongPress() {
		window.clearTimeout(longPressTimer)
		longPressTimer = null
		longPressOrigin = null
	}

	onBeforeUnmount(clearLongPress)

	function statusIcon(status) {
		if (status === 'Failed') return CircleAlert
		if (['Queued', 'Pending', 'Sending'].includes(status)) return Clock3
		if (status === 'Sent') return Check
		return CheckCheck
	}

	const content = computed(() => {
		if (typeof props.message.content === 'object') return props.message.content || {}
		try {
			return JSON.parse(props.message.content || '{}')
		} catch {
			return {}
		}
	})
	const richContent = computed(() => {
		const type = props.message.message_type
		return content.value.payload || content.value[type] || {}
	})
	const flowReply = computed(() => flowReplyFromContent(content.value))
	const hasFlowResponse = computed(
		() =>
			props.message.message_type === 'interactive' &&
			Boolean(flowReply.value.response || flowReply.value.body),
	)
	const mediaUrl = computed(() => {
		const value = String(
			props.message.media_url ||
				richContent.value?.local_file_url ||
				richContent.value?.link ||
				'',
		)
		return /^(https?:\/\/|\/)/i.test(value) ? value : ''
	})
	const quotedMessageId = computed(
		() =>
			content.value.context?.id ||
			content.value.context_message_id ||
			richContent.value.context_message_id ||
			'',
	)
	const quotedMessage = computed(
		() =>
			props.message.quoted_message || props.messageIndex.get(quotedMessageId.value) || null,
	)
	const quotedSender = computed(() => {
		if (!quotedMessage.value) return 'Original message'
		if (quotedMessage.value.direction === 'Outbound') {
			return quotedMessage.value.sender_name || 'You'
		}
		return props.contactName || 'Contact'
	})
	const quotedBody = computed(() => {
		const message = quotedMessage.value
		if (!message) return 'Original message unavailable'
		const body = String(message.body || '').trim()
		const labels = {
			image: 'Photo',
			sticker: 'Sticker',
			video: 'Video',
			audio: 'Audio',
			document: 'Document',
			location: 'Location',
			contacts: 'Contact',
			interactive: 'Interactive message',
			template: 'Template message',
		}
		if (message.message_type === 'text') return body || 'Message'
		const label = labels[message.message_type] || 'Message'
		return body && body !== `[${label}]` ? body : label
	})
	const quotedMediaUrl = computed(() => {
		if (!['image', 'sticker'].includes(quotedMessage.value?.message_type)) return ''
		const value = String(quotedMessage.value?.media_url || '')
		return /^(https?:\/\/|\/)/i.test(value) ? value : ''
	})
	const locationUrl = computed(() => {
		if (props.message.message_type !== 'location') return ''
		const latitude = richContent.value?.latitude
		const longitude = richContent.value?.longitude
		if (latitude === undefined || longitude === undefined) return ''
		return `https://www.google.com/maps?q=${encodeURIComponent(`${latitude},${longitude}`)}`
	})
	const contactNames = computed(() => {
		const rows = Array.isArray(richContent.value)
			? richContent.value
			: richContent.value?.contacts || []
		return rows
			.map((row) => row?.name?.formatted_name || row?.name?.first_name)
			.filter(Boolean)
			.join(', ')
	})
	const reactionGroups = computed(() => {
		const groups = new Map()
		for (const reaction of props.message.reactions || []) {
			if (!reaction?.emoji) continue
			const current = groups.get(reaction.emoji) || {
				emoji: reaction.emoji,
				count: 0,
				actors: [],
			}
			current.count += 1
			if (reaction.actor) current.actors.push(reaction.actor)
			groups.set(reaction.emoji, current)
		}
		return [...groups.values()]
	})

	function formatTime(value) {
		if (!value) return ''
		const date = new Date(String(value).replace(' ', 'T'))
		if (Number.isNaN(date.getTime())) return value
		const pad = (part) => String(part).padStart(2, '0')
		const period = date.getHours() >= 12 ? 'PM' : 'AM'
		const hour = date.getHours() % 12 || 12
		return `${pad(date.getDate())}-${pad(date.getMonth() + 1)}-${date.getFullYear()} ${pad(hour)}:${pad(date.getMinutes())}:${pad(date.getSeconds())} ${period}`
	}

	function readerInitials(reader) {
		const label = String(reader.full_name || reader.user || '').trim()
		return label
			.split(/\s+/)
			.slice(0, 2)
			.map((part) => part.charAt(0).toUpperCase())
			.join('') || '?'
	}
</script>

<template>
	<article
		:class="['message-bubble', message.direction?.toLowerCase()]"
		:data-message-name="message.name"
		@contextmenu="openMenu"
		@pointerdown="startLongPress"
		@pointermove="trackLongPress"
		@pointerup="clearLongPress"
		@pointercancel="clearLongPress"
	>
		<button
			class="message-menu-trigger"
			type="button"
			aria-label="Message actions"
			@click="openMenu"
		>
			<MoreVertical :size="15" />
		</button>
		<div v-if="message.direction === 'Outbound'" class="message-sender">
			{{ message.sender_name || message.owner || 'Team member' }}
		</div>
		<button
			v-if="quotedMessageId"
			class="quoted-message"
			type="button"
			:disabled="!quotedMessage"
			:aria-label="`Open replied message from ${quotedSender}`"
			@click.stop="quotedMessage && emit('quote', quotedMessage)"
		>
			<span>
				<strong>{{ quotedSender }}</strong>
				<small>{{ quotedBody }}</small>
			</span>
			<img
				v-if="quotedMediaUrl"
				:src="quotedMediaUrl"
				:alt="quotedBody"
				class="quoted-thumbnail"
			/>
		</button>
		<small v-if="message.message_type !== 'text' && !hasFlowResponse" class="message-kind">
			{{ message.message_type?.replaceAll('_', ' ') }}
		</small>
		<img
			v-if="['image', 'sticker'].includes(message.message_type) && mediaUrl"
			:src="mediaUrl"
			:alt="message.body || message.message_type"
			class="message-media image"
		/>
		<video
			v-else-if="message.message_type === 'video' && mediaUrl"
			:src="mediaUrl"
			class="message-media"
			controls
		/>
		<audio
			v-else-if="message.message_type === 'audio' && mediaUrl"
			:src="mediaUrl"
			class="message-audio"
			controls
		/>
		<a
			v-else-if="message.message_type === 'document' && mediaUrl"
			:href="mediaUrl"
			class="message-link"
			target="_blank"
			rel="noreferrer"
			>Open document</a
		>
		<a
			v-else-if="locationUrl"
			:href="locationUrl"
			class="message-link"
			target="_blank"
			rel="noreferrer"
			>Open location</a
		>
		<div v-else-if="message.message_type === 'contacts' && contactNames" class="contact-card">
			{{ contactNames }}
		</div>
		<FlowResponseCard
			v-else-if="hasFlowResponse"
			:response="flowReply.response"
			:heading="
				flowReply.name === 'flow' ? 'Flow response' : flowReply.name || 'Flow response'
			"
			:subtitle="flowReply.body"
			status="Submitted"
		/>
		<p v-else>{{ message.body || 'Media or interactive message' }}</p>
		<div v-if="message.ai_insight?.categories?.length" class="message-categories">
			<span
				v-for="category in message.ai_insight.categories"
				:key="category"
				class="message-category"
			>
				{{ category }}
			</span>
		</div>
		<details
			v-if="message.ai_insight?.transcript || message.ai_insight?.media_summary"
			class="message-insight"
		>
			<summary>
				{{ message.ai_insight.transcript ? 'Voice transcript' : 'Media summary' }}
			</summary>
			<p>{{ message.ai_insight.transcript || message.ai_insight.media_summary }}</p>
		</details>
		<div v-if="reactionGroups.length" class="message-reactions" aria-label="Reactions">
			<span
				v-for="reaction in reactionGroups"
				:key="reaction.emoji"
				:title="reaction.actors.join(', ')"
			>
				{{ reaction.emoji }}<small v-if="reaction.count > 1">{{ reaction.count }}</small>
			</span>
		</div>
		<footer>
			<time>{{ formatTime(message.provider_timestamp) }}</time>
			<button
				v-if="
					message.direction === 'Outbound' &&
					message.delivery_status === 'Failed' &&
					message.message_type === 'text'
				"
				class="reply-button retry-button"
				type="button"
				aria-label="Retry message"
				@click="$emit('retry', message)"
			>
				<RefreshCw :size="13" />
			</button>
			<button
				v-if="
					message.provider_message_id &&
					!message.provider_message_id.startsWith('local:')
				"
				class="reply-button"
				type="button"
				aria-label="Reply to message"
				@click="$emit('reply', message)"
			>
				<Reply :size="13" />
			</button>
			<span
				v-if="message.direction === 'Outbound'"
				:class="['delivery-mark', message.delivery_status?.toLowerCase()]"
				:aria-label="`Message ${message.delivery_status || 'queued'}`"
				:title="message.delivery_status || 'Queued'"
			>
				<component :is="statusIcon(message.delivery_status)" :size="13" />
			</span>
		</footer>
		<div v-if="readers.length" class="message-readers" aria-label="Read by team members">
			<span
				v-for="reader in readers"
				:key="reader.user"
				:title="`${reader.full_name || reader.user} read up to this message`"
			>
				<img v-if="reader.user_image" :src="reader.user_image" alt="" />
				<em v-else>{{ readerInitials(reader) }}</em>
			</span>
		</div>
	</article>
</template>

<style scoped>
	.message-bubble {
		position: relative;
		justify-self: start;
		width: fit-content;
		min-width: 0;
		max-width: min(72%, 620px);
		overflow-wrap: anywhere;
		padding: 10px 12px 7px;
		border: 1px solid var(--wa-border);
		border-radius: 14px 14px 14px 4px;
		background: var(--wa-message-in);
		box-shadow: 0 2px 8px rgba(16, 35, 29, 0.05);
	}
	.message-menu-trigger {
		position: absolute;
		top: 5px;
		right: 5px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 25px;
		height: 25px;
		padding: 0;
		border: 0;
		border-radius: 50%;
		background: color-mix(in srgb, var(--wa-surface) 88%, transparent);
		box-shadow: 0 1px 5px rgba(16, 35, 29, 0.1);
		color: var(--wa-muted);
		opacity: 0;
		cursor: pointer;
		transition:
			opacity 120ms ease,
			color 120ms ease,
			background 120ms ease;
	}
	.message-bubble:hover .message-menu-trigger,
	.message-menu-trigger:focus-visible {
		opacity: 1;
	}
	.message-menu-trigger:hover {
		color: var(--wa-text);
		background: var(--wa-surface);
	}
	.message-bubble.outbound {
		justify-self: end;
		border-color: color-mix(in srgb, var(--wa-green) 35%, var(--wa-border));
		border-radius: 14px 14px 4px 14px;
		background: var(--wa-message-out);
	}
	.message-insight {
		margin-top: 7px;
		padding-top: 7px;
		border-top: 1px solid var(--wa-border-soft);
		font-size: 11px;
	}
	.message-category {
		display: inline-flex;
		align-items: center;
		min-height: 20px;
		margin-top: 7px;
		padding: 2px 7px;
		border-radius: 999px;
		background: var(--wa-mint);
		color: var(--wa-primary);
		font-size: 10px;
		font-weight: 700;
		line-height: 1.2;
	}
	.message-categories {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-top: 7px;
	}
	.message-categories .message-category {
		margin-top: 0;
	}
	.message-insight summary {
		color: var(--wa-primary);
		font-weight: 700;
		cursor: pointer;
	}
	.message-insight p {
		margin: 6px 0 0;
		color: var(--wa-muted);
		line-height: 1.45;
	}
	.message-sender {
		margin-bottom: 4px;
		color: var(--wa-primary);
		font-size: 11px;
		font-weight: 650;
	}
	.quoted-message {
		display: flex;
		align-items: stretch;
		justify-content: space-between;
		width: 100%;
		margin-bottom: 6px;
		padding: 0;
		border: 0;
		border-left: 3px solid var(--wa-success);
		border-radius: 5px;
		text-align: left;
		color: var(--wa-muted);
		background: color-mix(in srgb, var(--wa-surface) 72%, transparent);
		font-size: 11px;
		overflow: hidden;
		cursor: pointer;
	}
	.quoted-message:disabled {
		cursor: default;
	}
	.quoted-message > span {
		display: grid;
		gap: 2px;
		min-width: 0;
		padding: 6px 8px;
	}
	.quoted-message strong {
		color: var(--wa-success);
		font-size: 11px;
		font-weight: 700;
	}
	.quoted-message small {
		display: -webkit-box;
		overflow: hidden;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 2;
		line-height: 1.35;
		overflow-wrap: anywhere;
	}
	.quoted-thumbnail {
		width: 54px;
		min-width: 54px;
		height: 54px;
		object-fit: cover;
		background: var(--wa-media-bg);
	}
	.message-bubble.quote-highlight {
		animation: quote-highlight 1.2s ease;
	}
	@keyframes quote-highlight {
		0%,
		100% {
			box-shadow: 0 2px 8px rgba(16, 35, 29, 0.05);
		}
		35% {
			box-shadow: 0 0 0 4px color-mix(in srgb, var(--wa-success) 30%, transparent);
		}
	}
	.message-media {
		display: block;
		width: min(360px, 100%);
		max-height: 320px;
		margin-bottom: 7px;
		border-radius: 9px;
		object-fit: contain;
		background: var(--wa-media-bg);
	}
	.message-media.image {
		object-fit: cover;
	}
	.message-audio {
		display: block;
		max-width: 100%;
		margin-bottom: 7px;
	}
	.message-link,
	.contact-card {
		display: block;
		margin-bottom: 7px;
		padding: 8px 9px;
		border-radius: 8px;
		color: var(--wa-success);
		background: color-mix(in srgb, var(--wa-surface) 82%, transparent);
		font-size: 11px;
		font-weight: 700;
		text-decoration: none;
	}
	p {
		margin: 0;
		white-space: pre-wrap;
		font-size: 13px;
		line-height: 1.5;
	}
	.message-reactions {
		position: absolute;
		left: 9px;
		bottom: -12px;
		display: flex;
		gap: 3px;
		z-index: 1;
	}
	.message-bubble.outbound .message-reactions {
		left: auto;
		right: 9px;
	}
	.message-reactions > span {
		display: inline-flex;
		align-items: center;
		gap: 2px;
		min-height: 23px;
		padding: 2px 7px;
		border: 1px solid var(--wa-border);
		border-radius: 999px;
		background: var(--wa-surface);
		box-shadow: 0 2px 6px rgba(16, 35, 29, 0.12);
		font-size: 13px;
	}
	.message-reactions small {
		color: var(--wa-muted);
		font-size: 10px;
	}
	.message-bubble:has(.message-reactions) {
		margin-bottom: 12px;
	}
	.message-kind {
		display: block;
		margin-bottom: 3px;
		color: var(--wa-green);
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
	}
	footer {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 5px;
		color: var(--wa-muted);
		font-size: 12px;
	}
	footer span {
		display: inline-flex;
		align-items: center;
		gap: 3px;
	}
	footer .failed {
		color: var(--wa-danger);
	}
	footer .read {
		color: #34b7f1;
	}
	.delivery-mark {
		min-width: 14px;
		justify-content: center;
	}
	.message-readers {
		position: absolute;
		right: 7px;
		bottom: -13px;
		display: flex;
		flex-direction: row-reverse;
		padding-left: 5px;
	}
	.message-readers > span {
		display: grid;
		place-items: center;
		width: 22px;
		height: 22px;
		margin-left: -5px;
		overflow: hidden;
		border: 2px solid var(--wa-surface);
		border-radius: 50%;
		background: var(--wa-primary);
		color: white;
		box-shadow: 0 1px 4px rgba(16, 35, 29, 0.14);
	}
	.message-readers img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.message-readers em {
		font-size: 8px;
		font-style: normal;
		font-weight: 800;
	}
	.message-bubble:has(.message-readers) {
		margin-bottom: 13px;
	}
	.reply-button {
		display: inline-flex;
		padding: 1px;
		border: 0;
		background: transparent;
		color: inherit;
		cursor: pointer;
	}
	.retry-button {
		color: var(--wa-danger);
	}
	@media (hover: none), (max-width: 760px) {
		.message-menu-trigger {
			opacity: 1;
		}
	}
	@media (max-width: 760px) {
		.message-bubble {
			max-width: 91%;
			padding: 9px 11px 7px;
		}
		.message-media {
			width: 100%;
			max-width: min(72vw, 360px);
			max-height: 42vh;
		}
		.message-audio {
			width: min(68vw, 310px);
		}
		footer {
			gap: 6px;
			font-size: 11px;
		}
	}
</style>
