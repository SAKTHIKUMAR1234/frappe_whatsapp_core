<script setup>
	import { computed, nextTick, ref } from 'vue'
	import Button from 'primevue/button'
	import {
		Clock3,
		FileText,
		PhoneIncoming,
		PhoneMissed,
		PhoneOutgoing,
		Play,
	} from 'lucide-vue-next'

	import { call as frappeCall, errorMessage } from '@/services/frappe'
	import { formatDateTime, parseDateTime } from '@/utils/datetime'

	const props = defineProps({
		call: { type: Object, required: true },
	})

	const loadingArtifact = ref('')
	const artifactError = ref('')
	const recordingUrl = ref(
		String(props.call.recording_url || '').startsWith('/private/files/')
			? props.call.recording_url
			: '',
	)
	const audio = ref(null)

	const normalizedStatus = computed(() => String(props.call.status || '').toLowerCase())
	const isFailed = computed(() =>
		['failed', 'missed', 'reject', 'rejected'].includes(normalizedStatus.value),
	)
	const statusLabel = computed(
		() =>
			({
				connect: 'Calling',
				connected: 'Connected',
				ringing: 'Ringing',
				pre_accept: 'Connecting',
				accept: 'Answered',
				accepted: 'Answered',
				terminate: 'Completed',
				terminated: 'Completed',
				ended: 'Completed',
				reject: 'Declined',
				rejected: 'Declined',
				missed: 'Missed',
				failed: 'Failed',
			})[normalizedStatus.value] ||
			(normalizedStatus.value ? normalizedStatus.value.replaceAll('_', ' ') : 'Call'),
	)
	const title = computed(
		() => `${props.call.direction === 'Inbound' ? 'Incoming' : 'Outgoing'} call`,
	)
	const timestamp = computed(
		() =>
			props.call.timeline_at ||
			props.call.started_at ||
			props.call.ended_at ||
			props.call.creation ||
			props.call.modified,
	)
	const duration = computed(() => {
		const start = parseDateTime(props.call.started_at)
		const end = parseDateTime(props.call.ended_at)
		if (!start || !end) return ''
		const seconds = Math.max(0, Math.round((end.getTime() - start.getTime()) / 1000))
		return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
	})

	async function loadArtifact(kind) {
		loadingArtifact.value = kind
		artifactError.value = ''
		try {
			const result = await frappeCall('frappe_whatsapp_core.calling.get_call_artifact', {
				call_name: props.call.name,
				kind,
				download: 1,
			})
			if (!result?.file_url) throw new Error(`${kind} is not available yet`)
			if (kind === 'recording') {
				recordingUrl.value = result.file_url
				await nextTick()
				await audio.value?.play().catch(() => {})
			} else {
				window.open(result.file_url, '_blank', 'noopener')
			}
		} catch (error) {
			artifactError.value = errorMessage(error, `Unable to open this call ${kind}.`)
		} finally {
			loadingArtifact.value = ''
		}
	}
</script>

<template>
	<article class="call-timeline-event" :class="{ failed: isFailed }" :data-call-name="call.name">
		<div class="call-icon" aria-hidden="true">
			<PhoneMissed v-if="isFailed" :size="20" />
			<PhoneIncoming v-else-if="call.direction === 'Inbound'" :size="20" />
			<PhoneOutgoing v-else :size="20" />
		</div>
		<div class="call-copy">
			<div class="call-heading">
				<strong>{{ title }}</strong>
				<span>{{ statusLabel }}</span>
			</div>
			<div class="call-meta">
				<span>{{ formatDateTime(timestamp) }}</span>
				<span v-if="duration"><Clock3 :size="12" />{{ duration }}</span>
				<span v-if="call.handled_by_name">Answered by {{ call.handled_by_name }}</span>
			</div>
			<div
				v-if="call.recording_media_id || call.recording_url || call.transcript_media_id"
				class="call-artifacts"
			>
				<Button
					v-if="(call.recording_media_id || call.recording_url) && !recordingUrl"
					label="Play recording"
					severity="secondary"
					text
					size="small"
					:loading="loadingArtifact === 'recording'"
					@click="loadArtifact('recording')"
				>
					<template #icon><Play :size="14" /></template>
				</Button>
				<Button
					v-if="call.transcript_media_id"
					label="Transcript"
					severity="secondary"
					text
					size="small"
					:loading="loadingArtifact === 'transcript'"
					@click="loadArtifact('transcript')"
				>
					<template #icon><FileText :size="14" /></template>
				</Button>
			</div>
			<audio
				v-if="recordingUrl"
				ref="audio"
				class="call-recording"
				:src="recordingUrl"
				controls
				preload="metadata"
			/>
			<small v-if="artifactError" class="artifact-error" role="alert">
				{{ artifactError }}
			</small>
		</div>
	</article>
</template>

<style scoped>
	.call-timeline-event {
		justify-self: center;
		width: min(440px, calc(100% - 24px));
		display: grid;
		grid-template-columns: 38px minmax(0, 1fr);
		gap: 10px;
		padding: 10px 12px;
		border: 1px solid var(--wa-border-soft);
		border-radius: 13px;
		color: var(--wa-text);
		background: color-mix(in srgb, var(--wa-surface) 94%, transparent);
		box-shadow: 0 4px 16px color-mix(in srgb, #000 8%, transparent);
	}
	.call-timeline-event.failed .call-icon,
	.call-timeline-event.failed .call-heading span {
		color: var(--wa-danger);
		background: var(--wa-danger-soft);
	}
	.call-icon {
		display: grid;
		place-items: center;
		width: 38px;
		height: 38px;
		border-radius: 50%;
		color: var(--wa-success);
		background: var(--wa-success-soft);
	}
	.call-copy,
	.call-heading,
	.call-meta,
	.call-artifacts {
		min-width: 0;
		display: flex;
	}
	.call-copy {
		flex-direction: column;
		gap: 5px;
	}
	.call-heading {
		align-items: center;
		justify-content: space-between;
		gap: 10px;
	}
	.call-heading strong {
		font-size: 13px;
	}
	.call-heading span {
		padding: 2px 7px;
		border-radius: 999px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
		font-size: 10px;
		font-weight: 650;
		text-transform: capitalize;
	}
	.call-meta {
		align-items: center;
		flex-wrap: wrap;
		gap: 5px 10px;
		color: var(--wa-muted);
		font-size: 11px;
	}
	.call-meta span {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.call-artifacts {
		align-items: center;
		flex-wrap: wrap;
		gap: 3px;
		margin-left: -8px;
	}
	.call-recording {
		width: 100%;
		height: 34px;
		margin-top: 2px;
	}
	.artifact-error {
		color: var(--wa-danger);
		font-size: 11px;
	}
</style>
