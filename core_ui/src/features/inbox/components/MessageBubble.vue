<script setup>
	import { computed } from 'vue'
	import {
		Check,
		CheckCheck,
		Clock3,
		CircleAlert,
		RefreshCw,
		Reply,
		Star,
	} from 'lucide-vue-next'

	const props = defineProps({
		message: { type: Object, required: true },
	})
	defineEmits(['reply', 'bookmark', 'retry'])

	function statusIcon(status) {
		if (status === 'Failed') return CircleAlert
		if (status === 'Queued') return Clock3
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
	const mediaUrl = computed(() => {
		const value = String(richContent.value?.link || '')
		return /^https?:\/\//i.test(value) ? value : ''
	})
	const quotedMessageId = computed(
		() =>
			content.value.context?.id ||
			content.value.context_message_id ||
			richContent.value.context_message_id ||
			'',
	)
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

	function formatTime(value) {
		if (!value) return ''
		const date = new Date(String(value).replace(' ', 'T'))
		if (Number.isNaN(date.getTime())) return value
		return new Intl.DateTimeFormat(undefined, {
			day: '2-digit',
			month: '2-digit',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
		}).format(date)
	}
</script>

<template>
	<article :class="['message-bubble', message.direction?.toLowerCase()]">
		<div v-if="quotedMessageId" class="quoted-message">Reply to {{ quotedMessageId }}</div>
		<small v-if="message.message_type !== 'text'" class="message-kind">
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
		<p>{{ message.body || 'Media or interactive message' }}</p>
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
				:class="['reply-button', { bookmarked: message.bookmarked }]"
				type="button"
				:aria-label="message.bookmarked ? 'Remove bookmark' : 'Bookmark message'"
				@click="$emit('bookmark', message)"
			>
				<Star :size="13" :fill="message.bookmarked ? 'currentColor' : 'none'" />
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
				:class="message.delivery_status?.toLowerCase()"
			>
				{{ message.delivery_status }}
				<component :is="statusIcon(message.delivery_status)" :size="13" />
			</span>
		</footer>
	</article>
</template>

<style scoped>
	.message-bubble {
		width: fit-content;
		max-width: min(72%, 620px);
		padding: 10px 12px 7px;
		border: 1px solid #e2e9e5;
		border-radius: 14px 14px 14px 4px;
		background: #fff;
		box-shadow: 0 2px 8px rgba(16, 35, 29, 0.05);
	}
	.message-bubble.outbound {
		margin-left: auto;
		border-color: #cdebdc;
		border-radius: 14px 14px 4px 14px;
		background: #dff7ea;
	}
	.quoted-message {
		margin-bottom: 6px;
		padding: 5px 7px;
		border-left: 3px solid #1a9a70;
		border-radius: 5px;
		color: #567068;
		background: rgba(255, 255, 255, 0.55);
		font-size: 9px;
	}
	.message-media {
		display: block;
		width: min(360px, 100%);
		max-height: 320px;
		margin-bottom: 7px;
		border-radius: 9px;
		object-fit: contain;
		background: #17211d;
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
		color: #0c7252;
		background: rgba(255, 255, 255, 0.72);
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
	.message-kind {
		display: block;
		margin-bottom: 3px;
		color: #147d58;
		font-size: 9px;
		font-weight: 700;
		text-transform: uppercase;
	}
	footer {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 5px;
		color: #7a8882;
		font-size: 9px;
	}
	footer span {
		display: inline-flex;
		align-items: center;
		gap: 3px;
	}
	footer .failed {
		color: #c2413b;
	}
	.reply-button {
		display: inline-flex;
		padding: 1px;
		border: 0;
		background: transparent;
		color: inherit;
		cursor: pointer;
	}
	.reply-button.bookmarked {
		color: #d18a00;
	}
	.retry-button {
		color: #c2413b;
	}
</style>
