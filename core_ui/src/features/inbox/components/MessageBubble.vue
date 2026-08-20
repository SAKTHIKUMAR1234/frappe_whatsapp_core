<script setup>
	import { computed, onBeforeUnmount, ref, watch } from 'vue'
	import Button from 'primevue/button'
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
	import MessageDocumentCard from '@/features/inbox/components/MessageDocumentCard.vue'
	import TemplateMessageCard from '@/features/inbox/components/TemplateMessageCard.vue'
	import { flowReplyFromContent } from '@/features/flows/utils/flowResponse'
	import { formatDateTime, formatTime } from '@/utils/datetime'

	const props = defineProps({
		message: { type: Object, required: true },
		messageIndex: { type: Map, default: () => new Map() },
		contactName: { type: String, default: 'Contact' },
		readers: { type: Array, default: () => [] },
	})
	const emit = defineEmits(['reply', 'retry', 'menu', 'quote'])
	let longPressTimer = null
	let longPressOrigin = null
	const readerOverlay = ref(null)
	const mediaReady = ref(false)
	const mediaFailed = ref(false)

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
	const templateSnapshot = computed(() => content.value.template_snapshot || {})
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
	const hasVisualMedia = computed(
		() =>
			['image', 'sticker', 'video'].includes(props.message.message_type) &&
			Boolean(mediaUrl.value),
	)
	watch(
		() => [props.message.name, props.message.message_type, mediaUrl.value],
		() => {
			mediaReady.value = false
			mediaFailed.value = false
		},
	)
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

	function readerInitials(reader) {
		const label = String(reader.display_name || reader.full_name || 'Team member').trim()
		return (
			label
				.split(/\s+/)
				.slice(0, 2)
				.map((part) => part.charAt(0).toUpperCase())
				.join('') || '?'
		)
	}

	function readerTooltip(reader) {
		const label = String(reader.display_name || reader.full_name || 'Team member').trim()
		const readAt = reader.last_read_at || reader.read_at
		const formatted = formatDateTime(readAt, '')
		return `${label || 'Team member'} read through this message${formatted ? ` · ${formatted}` : ''}`
	}

	function showReaderTooltip(event, reader) {
		const rect = event.currentTarget?.getBoundingClientRect?.()
		if (!rect) return
		const showAbove = rect.top > 76
		readerOverlay.value = {
			text: readerTooltip(reader),
			left: Math.max(150, Math.min(window.innerWidth - 150, rect.left + rect.width / 2)),
			top: showAbove ? rect.top - 8 : rect.bottom + 8,
			showAbove,
		}
	}

	function hideReaderTooltip() {
		readerOverlay.value = null
	}

	function markMediaReady() {
		mediaReady.value = true
		mediaFailed.value = false
	}

	function markMediaFailed() {
		mediaReady.value = false
		mediaFailed.value = true
	}
</script>

<template>
	<article
		:class="[
			'message-bubble',
			message.direction?.toLowerCase(),
			{ 'has-visual-media': hasVisualMedia },
		]"
		:data-message-name="message.name"
		@contextmenu="openMenu"
		@pointerdown="startLongPress"
		@pointermove="trackLongPress"
		@pointerup="clearLongPress"
		@pointercancel="clearLongPress"
	>
		<Button
			class="message-menu-trigger"
			unstyled
			aria-label="Message actions"
			@click="openMenu"
		>
			<MoreVertical :size="15" />
		</Button>
		<div v-if="message.direction === 'Outbound'" class="message-sender">
			{{ message.sender_name || message.owner || 'Team member' }}
		</div>
		<Button
			v-if="quotedMessageId"
			class="quoted-message"
			unstyled
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
		</Button>
		<small
			v-if="!['text', 'template'].includes(message.message_type) && !hasFlowResponse"
			class="message-kind"
		>
			{{ message.message_type?.replaceAll('_', ' ') }}
		</small>
		<div
			v-if="hasVisualMedia"
			:class="['message-media-frame', message.message_type, { ready: mediaReady }]"
		>
			<div v-if="!mediaReady && !mediaFailed" class="media-skeleton" aria-hidden="true" />
			<span v-if="mediaFailed" class="media-failed">Media unavailable</span>
			<img
				v-if="['image', 'sticker'].includes(message.message_type)"
				:src="mediaUrl"
				:alt="message.body || message.message_type"
				class="message-media"
				@load="markMediaReady"
				@error="markMediaFailed"
			/>
			<video
				v-else
				:src="mediaUrl"
				class="message-media"
				controls
				@loadedmetadata="markMediaReady"
				@error="markMediaFailed"
			/>
		</div>
		<audio
			v-else-if="message.message_type === 'audio' && mediaUrl"
			:src="mediaUrl"
			class="message-audio"
			controls
		/>
		<MessageDocumentCard
			v-else-if="message.message_type === 'document' && mediaUrl"
			:href="mediaUrl"
			:filename="richContent.filename || richContent.file_name || message.body"
			:mime-type="richContent.mime_type || richContent.mime"
			:size="Number(richContent.file_size || richContent.size || 0)"
		/>
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
		<TemplateMessageCard
			v-else-if="message.message_type === 'template'"
			:snapshot="templateSnapshot"
			:fallback="message.body"
			:media-url="mediaUrl"
			:media-type="richContent.mime_type"
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
			<Button
				v-if="
					message.direction === 'Outbound' &&
					message.delivery_status === 'Failed' &&
					message.message_type === 'text'
				"
				class="reply-button retry-button"
				unstyled
				aria-label="Retry message"
				@click="$emit('retry', message)"
			>
				<RefreshCw :size="13" />
			</Button>
			<Button
				v-if="
					message.provider_message_id &&
					!message.provider_message_id.startsWith('local:')
				"
				class="reply-button"
				unstyled
				aria-label="Reply to message"
				@click="$emit('reply', message)"
			>
				<Reply :size="13" />
			</Button>
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
				class="reader-avatar"
				:aria-label="readerTooltip(reader)"
				tabindex="0"
				@mouseenter="showReaderTooltip($event, reader)"
				@mouseleave="hideReaderTooltip"
				@focus="showReaderTooltip($event, reader)"
				@blur="hideReaderTooltip"
			>
				<img v-if="reader.user_image" :src="reader.user_image" alt="" />
				<em v-else>{{ readerInitials(reader) }}</em>
			</span>
		</div>
	</article>
	<Teleport to="body">
		<div
			v-if="readerOverlay"
			class="reader-tooltip-overlay"
			role="tooltip"
			:class="{ below: !readerOverlay.showAbove }"
			:style="{ left: `${readerOverlay.left}px`, top: `${readerOverlay.top}px` }"
		>
			{{ readerOverlay.text }}
		</div>
	</Teleport>
</template>

<style scoped>
	.message-bubble {
		position: relative;
		justify-self: start;
		width: fit-content;
		min-width: 0;
		max-width: min(72%, 620px);
		overflow-wrap: anywhere;
		padding: 7px 36px 5px 9px;
		border: 0;
		border-radius: 8px 8px 8px 2px;
		background: var(--wa-message-in);
		box-shadow: 0 1px 1px rgba(11, 20, 26, 0.16);
		animation: message-enter 160ms cubic-bezier(0.22, 1, 0.36, 1) both;
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
		border-radius: 8px 8px 2px 8px;
		background: var(--wa-message-out);
	}
	.message-bubble.has-visual-media {
		padding-right: 9px;
	}
	.message-bubble.has-visual-media .message-sender,
	.message-bubble.has-visual-media .message-kind {
		padding-right: 27px;
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
	.message-media-frame {
		position: relative;
		display: grid;
		width: min(360px, 68vw);
		aspect-ratio: 4 / 3;
		margin-bottom: 7px;
		border-radius: 9px;
		overflow: hidden;
		background: var(--wa-media-bg);
	}
	.message-media-frame.video {
		aspect-ratio: 16 / 9;
	}
	.message-media-frame.sticker {
		width: min(180px, 44vw);
		aspect-ratio: 1;
		background: transparent;
	}
	.message-media {
		grid-area: 1 / 1;
		display: block;
		width: 100%;
		height: 100%;
		object-fit: contain;
		opacity: 0;
		transition: opacity 140ms ease;
	}
	.message-media-frame.ready .message-media {
		opacity: 1;
	}
	.media-skeleton {
		grid-area: 1 / 1;
		background: linear-gradient(
			100deg,
			color-mix(in srgb, var(--wa-surface) 78%, transparent) 25%,
			color-mix(in srgb, var(--wa-border) 72%, transparent) 45%,
			color-mix(in srgb, var(--wa-surface) 78%, transparent) 65%
		);
		background-size: 220% 100%;
		animation: media-loading 1.15s ease-in-out infinite;
	}
	.media-failed {
		grid-area: 1 / 1;
		align-self: center;
		justify-self: center;
		color: var(--wa-muted);
		font-size: 12px;
	}
	@keyframes media-loading {
		to {
			background-position-x: -220%;
		}
	}
	.message-audio {
		display: block;
		max-width: 100%;
		margin-bottom: 7px;
	}
	.message-link,
	.contact-card {
		display: flex;
		align-items: center;
		min-height: 38px;
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
		font-size: 14.2px;
		line-height: 1.42;
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
		font-size: 11px;
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
		position: relative;
		display: grid;
		place-items: center;
		width: 22px;
		height: 22px;
		margin-left: -5px;
		border: 2px solid var(--wa-surface);
		border-radius: 50%;
		background: var(--wa-primary);
		color: white;
		box-shadow: 0 1px 4px rgba(16, 35, 29, 0.14);
		cursor: help;
		z-index: 1;
	}
	.message-readers > span:hover,
	.message-readers > span:focus-visible {
		z-index: 4;
		outline: 2px solid color-mix(in srgb, var(--wa-primary) 42%, transparent);
		outline-offset: 2px;
	}
	.reader-tooltip-overlay {
		position: fixed;
		z-index: 10050;
		width: max-content;
		max-width: min(300px, calc(100vw - 24px));
		padding: 6px 8px;
		border-radius: 6px;
		background: var(--wa-text);
		color: var(--wa-surface);
		box-shadow: 0 3px 12px rgba(11, 20, 26, 0.22);
		font-size: 11px;
		font-style: normal;
		font-weight: 600;
		line-height: 1.35;
		pointer-events: none;
		transform: translate(-50%, -100%);
		white-space: normal;
	}
	.reader-tooltip-overlay.below {
		transform: translate(-50%, 0);
	}
	.message-readers img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		border-radius: 50%;
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
	@keyframes message-enter {
		from {
			opacity: 0;
			transform: translateY(5px) scale(0.995);
		}
		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}
	@media (hover: none), (max-width: 760px) {
		.message-menu-trigger {
			opacity: 1;
		}
	}
	@media (max-width: 760px) {
		.message-bubble {
			max-width: 91%;
			padding: 9px 38px 7px 11px;
		}
		.message-media-frame {
			width: min(82vw, 360px);
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
