<script setup>
	import { computed } from 'vue'
	import Button from 'primevue/button'
	import { FileText, Image, Video } from 'lucide-vue-next'

	const props = defineProps({
		snapshot: { type: Object, default: () => ({}) },
		fallback: { type: String, default: '' },
		mediaUrl: { type: String, default: '' },
		mediaType: { type: String, default: '' },
	})
	const headerMedia = computed(() => props.mediaUrl || props.snapshot.header_media || '')
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
</script>

<template>
	<section class="template-message" aria-label="Template message">
		<img
			v-if="headerType === 'IMAGE' && isSafeUrl(headerMedia)"
			:src="headerMedia"
			alt="Template header"
			class="template-media"
		/>
		<video
			v-else-if="headerType === 'VIDEO' && isSafeUrl(headerMedia)"
			:src="headerMedia"
			class="template-media"
			controls
		/>
		<a
			v-else-if="headerType === 'DOCUMENT' && isSafeUrl(headerMedia)"
			:href="headerMedia"
			class="template-document"
			target="_blank"
			rel="noreferrer"
		>
			<FileText :size="18" />
			<span>Open document</span>
		</a>
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
	.template-media {
		display: block;
		width: calc(100% + 18px);
		max-height: 260px;
		margin: -7px -9px 8px;
		border-radius: 8px 8px 0 0;
		object-fit: cover;
		background: var(--wa-media-bg);
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
		min-height: 58px;
		margin: -2px 0 8px;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 7px;
		border-radius: 7px;
		color: var(--wa-primary);
		background: color-mix(in srgb, var(--wa-surface) 58%, transparent);
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
