<script setup>
	import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
	import { Download, ExternalLink, FileText, Minus, Plus, RotateCcw, X } from 'lucide-vue-next'

	const props = defineProps({
		visible: { type: Boolean, default: false },
		attachment: { type: Object, default: null },
	})
	const emit = defineEmits(['update:visible'])
	const closeButton = ref(null)
	const zoom = ref(1)
	let previousFocus = null
	let previousOverflow = ''

	const url = computed(() => String(props.attachment?.url || ''))
	const kind = computed(() => String(props.attachment?.kind || 'document').toLowerCase())
	const mimeType = computed(() => String(props.attachment?.mimeType || '').toLowerCase())
	const filename = computed(() => {
		const supplied = String(props.attachment?.filename || '').trim()
		if (supplied && !/^\[(image|document|video|sticker)\]$/i.test(supplied)) return supplied
		try {
			return decodeURIComponent(
				new URL(url.value, window.location.origin).pathname.split('/').pop(),
			)
		} catch {
			return ''
		}
	})
	const title = computed(() => filename.value || (kind.value === 'image' ? 'Photo' : 'Document'))
	const sizeLabel = computed(() => {
		const size = Number(props.attachment?.size || 0)
		if (!size) return ''
		if (size < 1024) return `${size} B`
		if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`
		return `${(size / 1024 ** 2).toFixed(1)} MB`
	})
	const metadata = computed(() =>
		[mimeType.value && mimeType.value.toUpperCase(), sizeLabel.value]
			.filter(Boolean)
			.join(' · '),
	)
	const isImage = computed(() => ['image', 'sticker'].includes(kind.value))
	const canInlineDocument = computed(() => {
		if (kind.value !== 'document') return false
		if (/^(application\/pdf|text\/|application\/(json|xml))/.test(mimeType.value)) return true
		return /\.(pdf|txt|csv|json|xml|html?)($|[?#])/i.test(url.value)
	})

	function close() {
		emit('update:visible', false)
	}

	function changeZoom(delta) {
		zoom.value = Math.min(3, Math.max(0.5, Number((zoom.value + delta).toFixed(2))))
	}

	function handleKeydown(event) {
		if (event.key === 'Escape') close()
		if (!isImage.value) return
		if (event.key === '+' || event.key === '=') changeZoom(0.25)
		if (event.key === '-') changeZoom(-0.25)
		if (event.key === '0') zoom.value = 1
	}

	watch(
		() => props.visible,
		async (visible) => {
			if (visible) {
				previousFocus = document.activeElement
				previousOverflow = document.body.style.overflow
				document.body.style.overflow = 'hidden'
				document.addEventListener('keydown', handleKeydown)
				await nextTick()
				closeButton.value?.focus?.()
				return
			}
			document.body.style.overflow = previousOverflow
			document.removeEventListener('keydown', handleKeydown)
			previousFocus?.focus?.()
		},
	)
	watch(
		() => props.attachment,
		() => (zoom.value = 1),
	)

	onBeforeUnmount(() => {
		document.body.style.overflow = previousOverflow
		document.removeEventListener('keydown', handleKeydown)
	})
</script>

<template>
	<Teleport to="body">
		<Transition name="attachment-preview">
			<section
				v-if="visible && url"
				class="attachment-preview"
				role="dialog"
				aria-modal="true"
				:aria-label="`Preview ${title}`"
				@click.self="close"
			>
				<header class="preview-toolbar">
					<div class="preview-title">
						<strong>{{ title }}</strong>
						<small v-if="metadata">{{ metadata }}</small>
					</div>
					<div v-if="isImage" class="zoom-controls" aria-label="Image zoom controls">
						<button type="button" aria-label="Zoom out" @click="changeZoom(-0.25)">
							<Minus :size="18" />
						</button>
						<span>{{ Math.round(zoom * 100) }}%</span>
						<button type="button" aria-label="Zoom in" @click="changeZoom(0.25)">
							<Plus :size="18" />
						</button>
						<button type="button" aria-label="Reset zoom" @click="zoom = 1">
							<RotateCcw :size="17" />
						</button>
					</div>
					<nav class="preview-actions" aria-label="Attachment actions">
						<a
							:href="url"
							target="_blank"
							rel="noreferrer"
							aria-label="Open in new tab"
						>
							<ExternalLink :size="18" />
						</a>
						<a
							:href="url"
							:download="filename || true"
							aria-label="Download attachment"
						>
							<Download :size="18" />
						</a>
						<button
							ref="closeButton"
							type="button"
							aria-label="Close preview"
							@click="close"
						>
							<X :size="21" />
						</button>
					</nav>
				</header>

				<main class="preview-stage">
					<img
						v-if="isImage"
						:src="url"
						:alt="title"
						:style="{ transform: `scale(${zoom})` }"
					/>
					<iframe
						v-else-if="canInlineDocument"
						:src="url"
						:title="`Document preview: ${title}`"
						sandbox="allow-same-origin"
						referrerpolicy="no-referrer"
					/>
					<div v-else class="unsupported-preview">
						<span><FileText :size="42" /></span>
						<strong>{{ title }}</strong>
						<p>This file type cannot be previewed safely in the browser.</p>
						<a :href="url" target="_blank" rel="noreferrer">
							<ExternalLink :size="17" /> Open document
						</a>
					</div>
				</main>
			</section>
		</Transition>
	</Teleport>
</template>

<style scoped>
	.attachment-preview {
		position: fixed;
		inset: 0;
		z-index: 12000;
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		color: #f8fafc;
		background: rgba(8, 15, 19, 0.96);
		backdrop-filter: blur(14px);
	}
	.preview-toolbar {
		min-height: 64px;
		padding: 10px 16px;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto;
		align-items: center;
		gap: 18px;
		border-bottom: 1px solid rgba(255, 255, 255, 0.1);
		background: rgba(10, 20, 24, 0.78);
	}
	.preview-title {
		min-width: 0;
		display: grid;
		gap: 2px;
	}
	.preview-title strong,
	.preview-title small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.preview-title strong {
		font-size: 14px;
	}
	.preview-title small {
		color: #94a3b8;
		font-size: 11px;
	}
	.zoom-controls,
	.preview-actions {
		display: flex;
		align-items: center;
		gap: 4px;
	}
	.zoom-controls span {
		width: 50px;
		text-align: center;
		color: #cbd5e1;
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}
	.preview-toolbar button,
	.preview-toolbar a {
		width: 38px;
		height: 38px;
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 50%;
		color: #e2e8f0;
		background: transparent;
		text-decoration: none;
		cursor: pointer;
		transition:
			background-color 140ms ease,
			color 140ms ease;
	}
	.preview-toolbar button:hover,
	.preview-toolbar button:focus-visible,
	.preview-toolbar a:hover,
	.preview-toolbar a:focus-visible {
		outline: 0;
		color: #fff;
		background: rgba(255, 255, 255, 0.11);
	}
	.preview-stage {
		min-height: 0;
		padding: 22px;
		display: grid;
		place-items: center;
		overflow: auto;
	}
	.preview-stage > img {
		max-width: min(100%, 1500px);
		max-height: calc(100vh - 110px);
		object-fit: contain;
		transform-origin: center;
		transition: transform 160ms ease;
		box-shadow: 0 24px 80px rgba(0, 0, 0, 0.32);
	}
	.preview-stage > iframe {
		width: min(1100px, 100%);
		height: 100%;
		min-height: 420px;
		border: 0;
		border-radius: 10px;
		background: #fff;
		box-shadow: 0 24px 80px rgba(0, 0, 0, 0.38);
	}
	.unsupported-preview {
		width: min(440px, 100%);
		padding: 38px 28px;
		display: grid;
		justify-items: center;
		gap: 12px;
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-radius: 16px;
		text-align: center;
		background: rgba(255, 255, 255, 0.06);
	}
	.unsupported-preview > span {
		width: 76px;
		height: 76px;
		display: grid;
		place-items: center;
		border-radius: 18px;
		color: #34d399;
		background: rgba(52, 211, 153, 0.12);
	}
	.unsupported-preview p {
		margin: 0;
		color: #94a3b8;
	}
	.unsupported-preview a {
		min-height: 40px;
		padding: 0 16px;
		display: inline-flex;
		align-items: center;
		gap: 7px;
		border-radius: 9px;
		color: #052e24;
		background: #34d399;
		font-weight: 700;
		text-decoration: none;
	}
	.attachment-preview-enter-active,
	.attachment-preview-leave-active {
		transition: opacity 150ms ease;
	}
	.attachment-preview-enter-from,
	.attachment-preview-leave-to {
		opacity: 0;
	}
	@media (max-width: 680px) {
		.preview-toolbar {
			grid-template-columns: minmax(0, 1fr) auto;
			gap: 8px;
			padding-inline: 10px;
		}
		.zoom-controls {
			position: fixed;
			left: 50%;
			bottom: 16px;
			z-index: 1;
			padding: 4px;
			border-radius: 999px;
			background: rgba(10, 20, 24, 0.86);
			transform: translateX(-50%);
		}
		.preview-actions a:first-child {
			display: none;
		}
		.preview-stage {
			padding: 12px;
		}
	}
</style>
