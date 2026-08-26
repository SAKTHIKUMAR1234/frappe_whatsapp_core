<script setup>
	import { computed, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import { FileText, Image, Video } from 'lucide-vue-next'

	const props = defineProps({
		snapshot: { type: Object, default: () => ({}) },
		fallback: { type: String, default: '' },
		mediaUrl: { type: String, default: '' },
		mediaType: { type: String, default: '' },
	})
	const emit = defineEmits(['preview'])
	const headerMedia = computed(() => props.mediaUrl || props.snapshot.header_media || '')
	const mediaReady = ref(false)
	const mediaFailed = ref(false)
	const headerType = computed(() => {
		const configured = String(props.snapshot.header_type || '').toUpperCase()
		if (configured) return configured
		const mime = String(props.mediaType || '').toLowerCase()
		if (mime.startsWith('image/')) return 'IMAGE'
		if (mime.startsWith('video/')) return 'VIDEO'
		return headerMedia.value ? 'DOCUMENT' : ''
	})

	function mediaIcon() {
		if (headerType.value === 'IMAGE') return Image
		if (headerType.value === 'VIDEO') return Video
		return FileText
	}

	function isSafeUrl(value) {
		return /^(https?:\/\/|\/)/i.test(String(value || ''))
	}

	function openPreview(kind) {
		if (!isSafeUrl(headerMedia.value)) return
		emit('preview', {
			url: headerMedia.value,
			kind,
			filename: props.snapshot.header_filename || props.snapshot.filename || '',
			mimeType: props.mediaType || '',
			size: Number(props.snapshot.header_file_size || 0),
		})
	}

	watch(
		() => [headerMedia.value, headerType.value],
		() => {
			mediaReady.value = false
			mediaFailed.value = false
		},
	)
</script>

<template>
	<section class="template-message" aria-label="Template message">
		<div
			v-if="['IMAGE', 'VIDEO'].includes(headerType) && isSafeUrl(headerMedia)"
			:class="['template-media-frame', { ready: mediaReady }]"
			:role="headerType === 'IMAGE' ? 'button' : undefined"
			:tabindex="headerType === 'IMAGE' ? 0 : undefined"
			@click="headerType === 'IMAGE' && openPreview('image')"
			@keydown.enter="headerType === 'IMAGE' && openPreview('image')"
			@keydown.space.prevent="headerType === 'IMAGE' && openPreview('image')"
		>
			<div v-if="!mediaReady && !mediaFailed" class="template-media-skeleton" />
			<span v-if="mediaFailed">Media unavailable</span>
			<img
				v-if="headerType === 'IMAGE'"
				:src="headerMedia"
				alt="Template header"
				class="template-media"
				@load="mediaReady = true"
				@error="mediaFailed = true"
			/>
			<video
				v-else
				:src="headerMedia"
				class="template-media"
				controls
				@loadedmetadata="mediaReady = true"
				@error="mediaFailed = true"
			/>
		</div>
		<button
			v-else-if="headerType === 'DOCUMENT' && isSafeUrl(headerMedia)"
			type="button"
			class="template-document"
			@click="openPreview('document')"
		>
			<FileText :size="18" />
			<span>Open document</span>
		</button>
		<div
			v-else-if="['IMAGE', 'VIDEO', 'DOCUMENT'].includes(headerType)"
			class="template-media-placeholder"
		>
			<component :is="mediaIcon()" :size="18" />
			<span>{{ headerType.toLowerCase() }} attachment</span>
		</div>
		<strong v-if="snapshot.header" class="template-header">{{ snapshot.header }}</strong>
		<p class="template-body">{{ snapshot.body || fallback || 'Template message' }}</p>
		<small v-if="snapshot.footer" class="template-footer">{{ snapshot.footer }}</small>
		<div v-if="snapshot.buttons?.length" class="template-buttons">
			<template
				v-for="(button, index) in snapshot.buttons"
				:key="`${button.label}-${index}`"
			>
				<Button
					v-if="button.url && isSafeUrl(button.url)"
					as="a"
					:href="button.url"
					target="_blank"
					rel="noreferrer"
					:label="button.label"
					text
					fluid
				/>
				<Button v-else :label="button.label" text fluid disabled />
			</template>
		</div>
	</section>
</template>

<style scoped>
	.template-message {
		min-width: min(270px, 62vw);
		max-width: 420px;
	}
	.template-media-frame {
		position: relative;
		display: grid;
		width: calc(100% + 18px);
		aspect-ratio: 16 / 9;
		margin: -7px -9px 8px;
		border-radius: 8px 8px 0 0;
		overflow: hidden;
		background: var(--wa-media-bg);
	}
	.template-media-frame[role='button'] {
		cursor: zoom-in;
	}
	.template-media-frame[role='button']:focus-visible {
		outline: 2px solid var(--wa-primary);
		outline-offset: 2px;
	}
	.template-media {
		grid-area: 1 / 1;
		display: block;
		width: 100%;
		height: 100%;
		object-fit: contain;
		opacity: 0;
		transition: opacity 140ms ease;
	}
	.template-media-frame.ready .template-media {
		opacity: 1;
	}
	.template-media-frame > span {
		grid-area: 1 / 1;
		align-self: center;
		justify-self: center;
		color: var(--wa-muted);
		font-size: 12px;
	}
	.template-media-skeleton {
		grid-area: 1 / 1;
		background: linear-gradient(
			100deg,
			color-mix(in srgb, var(--wa-surface) 78%, transparent) 25%,
			color-mix(in srgb, var(--wa-border) 72%, transparent) 45%,
			color-mix(in srgb, var(--wa-surface) 78%, transparent) 65%
		);
		background-size: 220% 100%;
		animation: template-media-loading 1.15s ease-in-out infinite;
	}
	@keyframes template-media-loading {
		to {
			background-position-x: -220%;
		}
	}
	.template-media-placeholder {
		min-height: 58px;
		margin: -2px 0 8px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 7px;
		border-radius: 7px;
		color: var(--wa-muted);
		background: color-mix(in srgb, var(--wa-surface) 58%, transparent);
		font-size: 12px;
		text-transform: capitalize;
	}
	.template-document {
		width: 100%;
		border: 0;
		min-height: 58px;
		margin: -2px 0 8px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 7px;
		border-radius: 7px;
		color: var(--wa-primary);
		background: color-mix(in srgb, var(--wa-surface) 58%, transparent);
		font: inherit;
		font-size: 12px;
		text-decoration: none;
	}
	.template-header,
	.template-body,
	.template-footer {
		display: block;
		white-space: pre-wrap;
	}
	.template-header {
		margin-bottom: 4px;
		font-size: 14.2px;
		font-weight: 650;
	}
	.template-body {
		margin: 0;
		font-size: 14.2px;
		line-height: 1.42;
	}
	.template-footer {
		margin-top: 5px;
		color: var(--wa-muted);
		font-size: 11px;
		line-height: 1.35;
	}
	.template-buttons {
		margin: 7px -9px -5px;
		border-top: 1px solid color-mix(in srgb, var(--wa-border) 74%, transparent);
	}
	.template-buttons :deep(.p-button) {
		min-height: 34px;
		border-radius: 0;
		color: var(--wa-primary);
		font-size: 13px;
	}
	.template-buttons :deep(.p-button + .p-button) {
		border-top: 1px solid color-mix(in srgb, var(--wa-border) 74%, transparent);
	}
</style>
