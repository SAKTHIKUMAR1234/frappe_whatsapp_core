<script setup>
	import { onErrorCaptured, ref } from 'vue'
	import Button from 'primevue/button'
	import { RefreshCw, TriangleAlert } from 'lucide-vue-next'

	const failure = ref(null)

	onErrorCaptured((error, instance, info) => {
		failure.value = {
			message: error?.message || 'The screen could not be rendered.',
			info,
		}
		console.error('WhatsApp Core UI render failure', error, info, instance)
		return false
	})

	function retry() {
		failure.value = null
		window.location.reload()
	}
</script>

<template>
	<slot v-if="!failure" />
	<main v-else class="fatal-error" role="alert">
		<span><TriangleAlert :size="28" /></span>
		<div>
			<p>WhatsApp Core</p>
			<h1>This screen ran into a problem</h1>
			<p>{{ failure.message }}</p>
			<Button label="Reload workspace" @click="retry">
				<template #icon><RefreshCw :size="16" /></template>
			</Button>
		</div>
	</main>
</template>

<style scoped>
	.fatal-error {
		min-height: 100dvh;
		padding: 32px;
		display: grid;
		place-content: center;
		grid-template-columns: 52px minmax(0, 440px);
		gap: 18px;
		background: #f5f7f6;
	}
	.fatal-error > span {
		width: 52px;
		height: 52px;
		display: grid;
		place-items: center;
		border-radius: 15px;
		color: #b42318;
		background: #fee4e2;
	}
	.fatal-error p:first-child {
		margin: 0;
		color: var(--wa-primary);
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}
	.fatal-error h1 {
		margin: 5px 0 8px;
		font-size: 25px;
	}
	.fatal-error p:not(:first-child) {
		margin: 0 0 20px;
		color: var(--wa-muted);
		line-height: 1.6;
	}
	@media (max-width: 600px) {
		.fatal-error {
			grid-template-columns: 1fr;
			place-content: center start;
		}
	}
</style>
