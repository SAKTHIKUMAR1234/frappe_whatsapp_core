<script setup>
	import { Check, CheckCheck, Clock3, CircleAlert } from 'lucide-vue-next'

	defineProps({
		message: { type: Object, required: true },
	})

	function statusIcon(status) {
		if (status === 'Failed') return CircleAlert
		if (status === 'Queued') return Clock3
		if (status === 'Sent') return Check
		return CheckCheck
	}
</script>

<template>
	<article :class="['message-bubble', message.direction?.toLowerCase()]">
		<p>{{ message.body || 'Media or interactive message' }}</p>
		<footer>
			<time>{{ message.provider_timestamp }}</time>
			<span
				v-if="message.direction === 'Outbound'"
				:class="message.delivery_status?.toLowerCase()"
			>
				{{ message.delivery_status }}
				<component :is="statusIcon(message.delivery_status)" :size="13" />
			</span>
		</footer>
	</article>
</template>

<style scoped>
	.message-bubble {
		width: fit-content;
		max-width: min(72%, 620px);
		padding: 10px 12px 7px;
		border: 1px solid #e2e9e5;
		border-radius: 14px 14px 14px 4px;
		background: #fff;
		box-shadow: 0 2px 8px rgba(16, 35, 29, 0.05);
	}
	.message-bubble.outbound {
		margin-left: auto;
		border-color: #cdebdc;
		border-radius: 14px 14px 4px 14px;
		background: #dff7ea;
	}
	p {
		margin: 0;
		white-space: pre-wrap;
		font-size: 13px;
		line-height: 1.5;
	}
	footer {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 5px;
		color: #7a8882;
		font-size: 9px;
	}
	footer span {
		display: inline-flex;
		align-items: center;
		gap: 3px;
	}
	footer .failed {
		color: #c2413b;
	}
</style>
