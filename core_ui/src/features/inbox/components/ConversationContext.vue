<script setup>
	import Select from 'primevue/select'
	import Tag from 'primevue/tag'
	import { Bot, Link2, UserRoundCheck } from 'lucide-vue-next'

	defineProps({
		data: { type: Object, required: true },
		canManage: { type: Boolean, default: false },
	})

	defineEmits(['status'])

	const statusOptions = ['Open', 'Pending', 'Resolved']
</script>

<template>
	<aside class="context-panel">
		<section>
			<div class="eyebrow">Conversation</div>
			<div class="identity">
				<span>{{ (data.display_name || 'WA').slice(0, 2).toUpperCase() }}</span>
				<div>
					<strong>{{ data.display_name }}</strong>
					<small>{{ data.identity?.normalized_value }}</small>
				</div>
			</div>
			<Select
				v-if="canManage"
				:model-value="data.conversation?.status"
				:options="statusOptions"
				class="status-select"
				@update:model-value="$emit('status', $event)"
			/>
			<span v-else class="status-readonly">{{ data.conversation?.status }}</span>
		</section>

		<section>
			<header><Link2 :size="15" /> Verified business links</header>
			<div v-if="data.party_bindings?.length" class="binding-list">
				<div v-for="binding in data.party_bindings" :key="binding.name">
					<strong>{{ binding.party_name }}</strong>
					<small>{{ binding.party_role || binding.party_doctype }}</small>
				</div>
			</div>
			<p v-else class="empty-copy">
				Unmapped. An operator or external AI can bind this identity.
			</p>
		</section>

		<section>
			<header><UserRoundCheck :size="15" /> Team visibility</header>
			<div class="reader-list">
				<Tag
					v-for="reader in data.readers"
					:key="reader.user"
					:value="reader.user"
					severity="secondary"
					rounded
				/>
				<span v-if="!data.readers?.length" class="empty-copy"
					>Not read by the team yet.</span
				>
			</div>
		</section>

		<section class="ai-note">
			<header><Bot :size="15" /> AI-ready context</header>
			<p>
				Messages, topic summaries and verified bindings are exposed through audited MCP
				tools.
			</p>
		</section>
	</aside>
</template>

<style scoped>
	.context-panel {
		min-height: 0;
		overflow-y: auto;
		border-left: 1px solid #e2e9e5;
		background: #fbfcfb;
	}
	section {
		padding: 17px;
		border-bottom: 1px solid #e7ece9;
	}
	section > header {
		display: flex;
		align-items: center;
		gap: 7px;
		margin-bottom: 12px;
		color: #52635b;
		font-size: 10px;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.identity {
		display: flex;
		align-items: center;
		gap: 10px;
		margin: 11px 0 13px;
	}
	.identity > span {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border-radius: 12px;
		color: #075e54;
		background: #dff7ea;
		font-size: 11px;
		font-weight: 800;
	}
	.identity strong,
	.identity small,
	.binding-list strong,
	.binding-list small {
		display: block;
	}
	.identity strong,
	.binding-list strong {
		font-size: 11px;
	}
	.identity small,
	.binding-list small {
		margin-top: 3px;
		color: #7a8881;
		font-size: 9px;
	}
	.status-select {
		width: 100%;
	}
	.status-readonly {
		display: inline-flex;
		padding: 5px 9px;
		border-radius: 999px;
		background: #eef4f1;
		color: #52635b;
		font-size: 10px;
		font-weight: 700;
	}
	.binding-list {
		display: grid;
		gap: 8px;
	}
	.binding-list > div {
		padding: 9px 10px;
		border: 1px solid #dfe8e3;
		border-radius: 10px;
		background: white;
	}
	.reader-list {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.ai-note {
		background: #f0faf6;
	}
	.ai-note p {
		margin: 0;
		color: #587269;
		font-size: 10px;
		line-height: 1.55;
	}
</style>
