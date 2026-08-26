<script setup>
	import Button from 'primevue/button'
	import { ShieldX } from 'lucide-vue-next'
	import { useSessionStore } from '@/stores/session'
	import { redirectToFrappeLogin } from '@/utils/frappeLogin'

	const session = useSessionStore()

	async function signOut() {
		await session.logout()
		redirectToFrappeLogin('/')
	}
</script>

<template>
	<main class="denied-page">
		<section>
			<div class="icon"><ShieldX :size="34" /></div>
			<p class="eyebrow">WhatsApp Core</p>
			<h1>Workspace access required</h1>
			<p>
				Your account is signed in, but it does not have the WhatsApp User or WhatsApp
				Manager role. Ask a System Manager to grant the appropriate role.
			</p>
			<Button label="Sign out" outlined @click="signOut" />
		</section>
	</main>
</template>

<style scoped>
	.denied-page {
		min-height: 100vh;
		display: grid;
		place-items: center;
		padding: 24px;
		background: var(--wa-bg);
		color: var(--wa-text);
	}
	section {
		width: min(520px, 100%);
		padding: 36px;
		border: 1px solid var(--wa-border);
		border-radius: 22px;
		background: var(--wa-surface);
		box-shadow: var(--wa-shadow-lg);
		text-align: center;
	}
	.icon {
		width: 64px;
		height: 64px;
		margin: 0 auto 18px;
		display: grid;
		place-items: center;
		border-radius: 20px;
		background: var(--wa-danger-soft);
		color: var(--wa-danger);
	}
	.eyebrow {
		margin: 0 0 8px;
		color: var(--wa-primary);
		font-size: 0.78rem;
		font-weight: 800;
		letter-spacing: 0.12em;
		text-transform: uppercase;
	}
	h1 {
		margin: 0 0 12px;
		font-size: clamp(1.7rem, 5vw, 2.35rem);
	}
	section > p:not(.eyebrow) {
		margin: 0 auto 24px;
		color: var(--wa-muted);
		line-height: 1.7;
	}
</style>
