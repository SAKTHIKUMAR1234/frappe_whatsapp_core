<script setup>
	import { computed, ref } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import InputText from 'primevue/inputtext'
	import Password from 'primevue/password'
	import Message from 'primevue/message'
	import CoreMark from '@/components/CoreMark.vue'
	import { useSessionStore } from '@/stores/session'
	import { errorMessage } from '@/services/frappe'

	const session = useSessionStore()
	const route = useRoute()
	const router = useRouter()
	const email = ref('')
	const password = ref('')
	const error = ref('')
	const submitting = ref(false)
	const attempted = ref(false)
	const sessionNotice = computed(() =>
		route.query.expired
			? 'Your session expired. Sign in again to continue.'
			: route.query.unavailable
				? 'WhatsApp Core could not be reached. Check the server and try again.'
				: '',
	)

	async function submit() {
		attempted.value = true
		error.value = ''
		if (!email.value.trim() || !password.value) return
		submitting.value = true
		try {
			await session.login(email.value, password.value)
			router.push(route.query.redirect || '/')
		} catch (exception) {
			error.value = errorMessage(exception, 'Unable to sign in with those credentials.')
		} finally {
			submitting.value = false
		}
	}
</script>

<template>
	<main class="login-page">
		<section class="login-art">
			<div class="art-copy">
				<div class="art-logo"><CoreMark :size="53" /></div>
				<span>WhatsApp Core</span>
				<h1>One place to handle every WhatsApp interaction.</h1>
				<p>
					Handle conversations, groups, calling, campaigns and customer experiences in
					one workspace.
				</p>
			</div>
			<div class="art-flow">
				<div>Trigger</div>
				<i></i>
				<div>Ask</div>
				<i></i>
				<div>Branch</div>
				<i></i>
				<div>Action</div>
			</div>
		</section>
		<section class="login-panel">
			<form @submit.prevent="submit">
				<div class="eyebrow">Messaging workspace</div>
				<h2>Welcome back</h2>
				<p>Sign in with your Frappe account.</p>
				<Message v-if="sessionNotice" severity="warn" :closable="false">{{
					sessionNotice
				}}</Message>
				<label>Email or username</label>
				<InputText
					v-model="email"
					type="text"
					autocomplete="username"
					placeholder="you@company.com or Administrator"
					fluid
					autofocus
					:invalid="attempted && !email.trim()"
				/>
				<small v-if="attempted && !email.trim()" class="field-error"
					>Enter your email address or username.</small
				>
				<label>Password</label>
				<Password
					v-model="password"
					autocomplete="current-password"
					:feedback="false"
					toggle-mask
					fluid
					placeholder="Your password"
					:invalid="attempted && !password"
				/>
				<small v-if="attempted && !password" class="field-error"
					>Enter your password.</small
				>
				<Message v-if="error" severity="error" :closable="false">{{ error }}</Message>
				<Button
					type="submit"
					label="Sign in to WhatsApp Core"
					:loading="submitting"
					fluid
				/>
				<small>Secured by your company account and role permissions.</small>
			</form>
		</section>
	</main>
</template>

<style scoped>
	.login-page {
		min-height: 100vh;
		display: grid;
		grid-template-columns: 1.15fr 0.85fr;
		color-scheme: dark;
		color: #eaeef4;
		background: #1a1d20;
	}
	.login-art {
		position: relative;
		display: flex;
		flex-direction: column;
		justify-content: center;
		padding: clamp(48px, 7vw, 100px);
		overflow: hidden;
		color: white;
		background:
			radial-gradient(circle at 16% 12%, rgb(63 182 222 / 22%) 0, transparent 31%),
			linear-gradient(rgb(57 64 71 / 26%) 1px, transparent 1px),
			linear-gradient(90deg, rgb(57 64 71 / 26%) 1px, transparent 1px), #121517;
		background-size:
			auto,
			64px 64px,
			64px 64px,
			auto;
	}
	.login-art:after {
		content: '';
		position: absolute;
		width: 520px;
		height: 520px;
		right: -220px;
		bottom: -220px;
		border: 1px solid rgb(63 182 222 / 42%);
		border-radius: 50%;
		box-shadow:
			0 0 0 80px rgb(63 182 222 / 7%),
			0 0 0 160px rgb(63 182 222 / 4%);
	}
	.art-copy {
		max-width: 620px;
		position: relative;
		z-index: 1;
	}
	.art-logo {
		width: 53px;
		height: 53px;
		display: grid;
		place-items: center;
		border-radius: 7px;
		background: transparent;
		margin-bottom: 25px;
	}
	.art-copy > span {
		color: #3fb6de;
		text-transform: uppercase;
		letter-spacing: 0.13em;
		font-size: 11px;
		font-weight: 800;
	}
	.art-copy h1 {
		font-size: clamp(42px, 4.3vw, 66px);
		line-height: 1.02;
		letter-spacing: -0.04em;
		font-weight: 800;
		margin: 14px 0 18px;
	}
	.art-copy p {
		max-width: 520px;
		color: #9aa6b2;
		font-size: 16px;
		line-height: 1.7;
	}
	.art-flow {
		position: relative;
		z-index: 1;
		margin-top: 55px;
		display: flex;
		align-items: center;
		gap: 11px;
	}
	.art-flow div {
		padding: 9px 14px;
		border: 1px solid #394047;
		border-radius: 2px;
		color: #eaeef4;
		background: rgb(26 29 32 / 82%);
		font-size: 11px;
		font-weight: 700;
	}
	.art-flow i {
		width: 34px;
		height: 1px;
		background: #3fb6de;
	}
	.login-panel {
		display: grid;
		place-items: center;
		padding: 40px;
		border-left: 1px solid #2b3035;
		background:
			radial-gradient(circle at 100% 0, rgb(63 182 222 / 9%), transparent 38%), #1a1d20;
	}
	.login-panel form {
		width: min(390px, 100%);
		animation: login-form-in 950ms cubic-bezier(0.16, 1, 0.3, 1) both;
	}
	form h2 {
		font-size: 30px;
		margin: 10px 0 5px;
	}
	form > p {
		margin: 0 0 30px;
		color: #9aa6b2;
		font-size: 13px;
	}
	label {
		display: block;
		margin: 17px 0 7px;
		font-size: 11px;
		font-weight: 700;
	}
	.error {
		margin: 14px 0;
		padding: 9px 11px;
		border-radius: 9px;
		background: var(--wa-danger-soft);
		color: var(--wa-danger);
		font-size: 11px;
	}
	.field-error {
		display: block;
		margin-top: 6px;
		color: var(--wa-danger);
		font-size: 11px;
	}
	form :deep(.p-message) {
		margin: 14px 0;
	}
	form > .p-button {
		margin-top: 22px;
	}
	form > small {
		display: block;
		margin-top: 22px;
		text-align: center;
		color: #7f8993;
		font-size: 12px;
	}
	.login-panel :deep(.p-inputtext),
	.login-panel :deep(.p-password-input) {
		border-color: #394047;
		border-radius: 3px;
		color: #eaeef4;
		background: #15181b;
	}
	.login-panel :deep(.p-inputtext:focus),
	.login-panel :deep(.p-password-input:focus) {
		border-color: #3fb6de;
		box-shadow: 0 0 0 2px rgb(63 182 222 / 18%);
	}
	.login-panel :deep(.p-button) {
		border-color: #087fa8;
		border-radius: 3px;
		background: #087fa8;
		transition:
			transform 450ms cubic-bezier(0.16, 1, 0.3, 1),
			background-color 450ms cubic-bezier(0.16, 1, 0.3, 1);
	}
	.login-panel :deep(.p-button:hover) {
		transform: translateY(-1px);
		background: #0a90bd;
	}
	@keyframes login-form-in {
		from {
			opacity: 0;
			transform: translateY(12px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
	@media (max-width: 800px) {
		.login-page {
			grid-template-columns: 1fr;
		}
		.login-art {
			display: none;
		}
		.login-panel {
			min-height: 100vh;
		}
	}
</style>
