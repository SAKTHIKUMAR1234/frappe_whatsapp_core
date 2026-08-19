<script setup>
	import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
	import Button from 'primevue/button'
	import { Mic, MicOff, Phone, PhoneOff } from 'lucide-vue-next'
	import { useCallingStore } from '@/stores/calling'
	import {
		startRingtone,
		stopRingtone,
		unlockRingtone,
	} from '@/features/calling/services/callRingtone'

	const calling = useCallingStore()
	const remoteAudio = ref(null)
	const action = ref('')
	const actionError = ref('')

	const visibleCall = computed(() => calling.active || calling.incoming)
	const title = computed(
		() =>
			visibleCall.value?.display_name ||
			visibleCall.value?.presentation?.display_name ||
			visibleCall.value?.remote_username ||
			visibleCall.value?.remote_number ||
			'WhatsApp contact',
	)
	const subtitle = computed(() => {
		if (calling.incoming && !calling.active) return 'Incoming WhatsApp call'
		const phase = calling.active?.phase || 'connecting'
		return (
			{
				preparing: 'Preparing microphone…',
				calling: 'Calling…',
				answering: 'Answering…',
				pre_accepting: 'Securing audio…',
				connecting: 'Connecting audio…',
				accepting: 'Starting call…',
				connected: duration(calling.elapsedSeconds),
				ending: 'Ending call…',
			}[phase] || 'WhatsApp call'
		)
	})

	function duration(seconds) {
		const minutes = Math.floor(Number(seconds || 0) / 60)
		const remainder = Number(seconds || 0) % 60
		return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
	}

	async function run(name, callback) {
		action.value = name
		actionError.value = ''
		try {
			await callback()
		} catch (error) {
			actionError.value = error?.message || 'The call action failed.'
		} finally {
			action.value = ''
		}
	}

	watch(
		() => calling.remoteStream,
		async (stream) => {
			await nextTick()
			if (!remoteAudio.value) return
			remoteAudio.value.srcObject = stream || null
			if (stream) remoteAudio.value.play().catch(() => {})
		},
		{ flush: 'post' },
	)

	watch(
		() => Boolean(calling.incoming && !calling.active),
		(ringing) => {
			if (ringing) startRingtone()
			else stopRingtone()
		},
		{ immediate: true },
	)

	async function unlockCallSound() {
		if (!(await unlockRingtone())) return
		window.removeEventListener('pointerdown', unlockCallSound)
		window.removeEventListener('keydown', unlockCallSound)
	}

	onMounted(() => {
		// Browsers permit audible realtime notifications only after a user gesture.
		// Unlock once while the operator is using the workspace, before a call arrives.
		window.addEventListener('pointerdown', unlockCallSound)
		window.addEventListener('keydown', unlockCallSound)
	})

	onUnmounted(() => {
		window.removeEventListener('pointerdown', unlockCallSound)
		window.removeEventListener('keydown', unlockCallSound)
		stopRingtone()
	})
</script>

<template>
	<Transition name="call-dock">
		<aside v-if="visibleCall" class="call-dock" aria-live="assertive">
			<audio ref="remoteAudio" autoplay playsinline />
			<div class="contact-avatar">{{ title.slice(0, 1).toUpperCase() }}</div>
			<div class="call-copy">
				<strong>{{ title }}</strong>
				<span>{{ subtitle }}</span>
				<small v-if="actionError">{{ actionError }}</small>
			</div>
			<div v-if="calling.incoming && !calling.active" class="call-actions">
				<Button
					title="Decline call"
					rounded
					severity="danger"
					aria-label="Decline call"
					:loading="action === 'decline'"
					@click="run('decline', () => calling.declineCall())"
				>
					<PhoneOff :size="19" />
				</Button>
				<Button
					title="Answer call"
					class="answer-button"
					rounded
					aria-label="Answer call"
					:loading="action === 'answer'"
					@click="run('answer', () => calling.answerCall())"
				>
					<Phone :size="19" />
				</Button>
			</div>
			<div v-else class="call-actions">
				<Button
					:title="calling.muted ? 'Unmute' : 'Mute'"
					rounded
					severity="secondary"
					:aria-label="calling.muted ? 'Unmute call' : 'Mute call'"
					@click="calling.toggleMute()"
				>
					<MicOff v-if="calling.muted" :size="19" />
					<Mic v-else :size="19" />
				</Button>
				<Button
					title="End call"
					rounded
					severity="danger"
					aria-label="End call"
					:loading="action === 'hangup'"
					@click="run('hangup', () => calling.hangUp())"
				>
					<PhoneOff :size="19" />
				</Button>
			</div>
		</aside>
	</Transition>
</template>

<style scoped>
	.call-dock {
		position: fixed;
		top: 68px;
		right: 18px;
		z-index: 90;
		width: min(420px, calc(100vw - 36px));
		min-height: 78px;
		padding: 13px 14px;
		display: grid;
		grid-template-columns: 50px minmax(0, 1fr) auto;
		gap: 12px;
		align-items: center;
		border: 1px solid color-mix(in srgb, var(--wa-primary) 35%, var(--wa-border));
		border-radius: 16px;
		background: color-mix(in srgb, var(--wa-surface) 96%, transparent);
		box-shadow: 0 18px 55px rgb(15 23 42 / 22%);
		backdrop-filter: blur(18px);
	}
	.contact-avatar {
		width: 50px;
		height: 50px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		background: var(--wa-primary-soft);
		color: var(--wa-primary);
		font-size: 18px;
		font-weight: 800;
	}
	.call-copy {
		min-width: 0;
		display: grid;
		gap: 3px;
	}
	.call-copy strong,
	.call-copy span,
	.call-copy small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.call-copy strong {
		font-size: 14px;
		color: var(--wa-text);
	}
	.call-copy span {
		font-size: 12px;
		color: var(--wa-muted);
	}
	.call-copy small {
		color: var(--wa-danger, #dc2626);
		font-size: 11px;
	}
	.call-actions {
		display: flex;
		gap: 8px;
	}
	.answer-button {
		background: var(--wa-green) !important;
		border-color: var(--wa-green) !important;
	}
	.call-dock-enter-active,
	.call-dock-leave-active {
		transition: 180ms ease;
	}
	.call-dock-enter-from,
	.call-dock-leave-to {
		opacity: 0;
		transform: translateY(-12px) scale(0.98);
	}
	@media (max-width: 640px) {
		.call-dock {
			top: auto;
			bottom: 16px;
			left: 12px;
			right: 12px;
			width: auto;
		}
	}
</style>
