<script setup>
	import { computed } from 'vue'
	import {
		Download,
		FileArchive,
		FileSpreadsheet,
		FileText,
		Presentation,
	} from 'lucide-vue-next'

	const props = defineProps({
		href: { type: String, required: true },
		filename: { type: String, default: '' },
		mimeType: { type: String, default: '' },
		size: { type: Number, default: 0 },
	})

	const displayName = computed(() => {
		if (props.filename) return props.filename
		try {
			return (
				decodeURIComponent(
					new URL(props.href, window.location.origin).pathname.split('/').pop(),
				) || 'Document'
			)
		} catch {
			return 'Document'
		}
	})
	const extension = computed(() => {
		const nameParts = displayName.value.split('.')
		if (nameParts.length > 1) return nameParts.pop()?.toUpperCase() || 'FILE'
		return props.mimeType.split('/').pop()?.toUpperCase() || 'FILE'
	})
	const icon = computed(() => {
		const name = displayName.value.toLowerCase()
		if (/\.(xls|xlsx|csv)$/.test(name)) return FileSpreadsheet
		if (/\.(ppt|pptx)$/.test(name)) return Presentation
		if (/\.(zip|rar|7z|tar|gz)$/.test(name)) return FileArchive
		return FileText
	})
	const sizeLabel = computed(() => {
		if (!props.size) return ''
		if (props.size < 1024) return `${props.size} B`
		if (props.size < 1024 ** 2) return `${(props.size / 1024).toFixed(1)} KB`
		return `${(props.size / 1024 ** 2).toFixed(1)} MB`
	})
</script>

<template>
	<a :href="href" class="document-card" target="_blank" rel="noreferrer">
		<span class="document-icon"><component :is="icon" :size="20" /></span>
		<span class="document-copy">
			<strong>{{ displayName }}</strong>
			<small>{{ [extension, sizeLabel].filter(Boolean).join(' · ') }}</small>
		</span>
		<span class="download-icon" aria-hidden="true"><Download :size="17" /></span>
	</a>
</template>

<style scoped>
	.document-card {
		width: min(360px, 68vw);
		min-height: 58px;
		margin-bottom: 7px;
		padding: 8px;
		display: grid;
		grid-template-columns: 40px minmax(0, 1fr) 30px;
		align-items: center;
		gap: 9px;
		border: 1px solid color-mix(in srgb, var(--wa-border) 72%, transparent);
		border-radius: 9px;
		color: var(--wa-text);
		background: color-mix(in srgb, var(--wa-surface) 82%, transparent);
		text-decoration: none;
		transition:
			border-color 140ms ease,
			background-color 140ms ease,
			transform 140ms ease;
	}
	.document-card:hover,
	.document-card:focus-visible {
		border-color: color-mix(in srgb, var(--wa-primary) 42%, var(--wa-border));
		background: var(--wa-surface);
		transform: translateY(-1px);
		outline: 0;
	}
	.document-icon {
		width: 40px;
		height: 40px;
		display: grid;
		place-items: center;
		border-radius: 9px;
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
	}
	.document-copy {
		min-width: 0;
		display: grid;
		gap: 3px;
	}
	.document-copy strong {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12px;
	}
	.document-copy small {
		color: var(--wa-muted);
		font-size: 10px;
		font-weight: 700;
	}
	.download-icon {
		width: 30px;
		height: 30px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		color: var(--wa-muted);
	}
	.document-card:hover .download-icon {
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
	}
	@media (max-width: 760px) {
		.document-card {
			width: min(78vw, 360px);
		}
	}
</style>
