<script setup>
	import { computed, ref } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import InputText from 'primevue/inputtext'
	import Password from 'primevue/password'
	import Message from 'primevue/message'
	import { MessageCircleMore } from 'lucide-vue-next'
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
				? 'The Frappe site could not be reached. Check the server and try again.'
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
				<div class="art-logo"><MessageCircleMore :size="28" /></div>
				<span>WhatsApp Core</span>
				<h1>One place to configure every WhatsApp interaction.</h1>
				<p>
					Build flows, run campaigns, review AI queues and launch polls—without touching
					the relay server.
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
				<div class="eyebrow">Company workspace</div>
				<h2>Welcome back</h2>
				<p>Sign in with your Frappe account.</p>
				<Message v-if="sessionNotice" severity="warn" :closable="false">{{
					sessionNotice
				}}</Message>
				<label>Email</label>
				<InputText
					v-model="email"
					type="email"
					placeholder="you@company.com"
					fluid
					autofocus
					:invalid="attempted && !email.trim()"
				/>
				<small v-if="attempted && !email.trim()" class="field-error"
					>Enter your email address.</small
				>
				<label>Password</label>
				<Password
					v-model="password"
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
				<small>Secured by your company’s Frappe site and role permissions.</small>
			</form>
		</section>
	</main>
</template>

<style scoped>
	.login-page {
		min-height: 100vh;
		display: grid;
		grid-template-columns: 1.15fr 0.85fr;
		background: white;
	}
	.login-art {
		position: relative;
		display: flex;
		flex-direction: column;
		justify-content: center;
		padding: 80px;
		overflow: hidden;
		color: white;
		background:
			radial-gradient(circle at 20% 10%, #268f70 0, transparent 30%),
			linear-gradient(145deg, #102f26, #071c16);
	}
	.login-art:after {
		content: '';
		position: absolute;
		width: 520px;
		height: 520px;
		right: -220px;
		bottom: -220px;
		border: 1px solid #3d695a;
		border-radius: 50%;
		box-shadow:
			0 0 0 80px #173e321f,
			0 0 0 160px #173e3215;
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
		border-radius: 17px;
		background: #76efbf;
		color: #0a372a;
		margin-bottom: 25px;
	}
	.art-copy > span {
		color: #8dbdad;
		text-transform: uppercase;
		letter-spacing: 0.13em;
		font-size: 11px;
		font-weight: 800;
	}
	.art-copy h1 {
		font-size: 46px;
		line-height: 1.08;
		letter-spacing: -1.5px;
		margin: 14px 0 18px;
	}
	.art-copy p {
		max-width: 520px;
		color: #a9c5bb;
		font-size: 15px;
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
		border: 1px solid #41685b;
		border-radius: 10px;
		color: #d4e7df;
		background: #183b30;
		font-size: 11px;
		font-weight: 700;
	}
	.art-flow i {
		width: 34px;
		height: 1px;
		background: #5d8779;
	}
	.login-panel {
		display: grid;
		place-items: center;
		padding: 40px;
	}
	.login-panel form {
		width: min(390px, 100%);
	}
	form h2 {
		font-size: 30px;
		margin: 10px 0 5px;
	}
	form > p {
		margin: 0 0 30px;
		color: #78857f;
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
		background: #fff0f0;
		color: #b42318;
		font-size: 11px;
	}
	.field-error {
		display: block;
		margin-top: 6px;
		color: #b42318;
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
		color: #9aa49f;
		font-size: 10px;
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
