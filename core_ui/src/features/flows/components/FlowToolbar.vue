<script setup>
	import Button from 'primevue/button'
	import Tag from 'primevue/tag'
	import { ArrowLeft, CheckCircle2, Play, Save } from 'lucide-vue-next'

	defineProps({
		flow: {
			type: Object,
			required: true,
		},
		saving: Boolean,
		validating: Boolean,
		publishing: Boolean,
	})

	defineEmits(['back', 'open-triggers', 'save', 'validate', 'publish'])
</script>

<template>
	<header class="flow-toolbar">
		<Button text rounded @click="$emit('back')">
			<ArrowLeft :size="18" />
		</Button>

		<div class="flow-title">
			<div>
				<span>Flow Builder</span>
				<strong>{{ flow.title }}</strong>
			</div>
			<Tag
				:value="flow.status"
				:severity="flow.status === 'Published' ? 'success' : 'warn'"
				rounded
			/>
		</div>

		<div class="toolbar-actions">
			<Button label="Triggers" severity="secondary" outlined @click="$emit('open-triggers')">
				<template #icon><Play :size="15" /></template>
			</Button>
			<Button
				label="Validate"
				severity="secondary"
				:loading="validating"
				@click="$emit('validate')"
			>
				<template #icon><CheckCircle2 :size="15" /></template>
			</Button>
			<Button
				label="Save draft"
				severity="secondary"
				outlined
				:loading="saving"
				@click="$emit('save')"
			>
				<template #icon><Save :size="15" /></template>
			</Button>
			<Button label="Publish" :loading="publishing" @click="$emit('publish')" />
		</div>
	</header>
</template>

<style scoped>
	.flow-toolbar {
		height: 66px;
		padding: 0 16px;
		display: flex;
		align-items: center;
		gap: 11px;
		border-bottom: 1px solid var(--wa-border);
		background: white;
	}

	.flow-title {
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 11px;
	}

	.flow-title span,
	.flow-title strong {
		display: block;
	}

	.flow-title span {
		color: #86928c;
		font-size: 8px;
		text-transform: uppercase;
		letter-spacing: 0.09em;
	}

	.flow-title strong {
		max-width: 280px;
		margin-top: 2px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12px;
	}

	.toolbar-actions {
		margin-left: auto;
		display: flex;
		gap: 8px;
	}

	@media (max-width: 1050px) {
		.toolbar-actions :deep(.p-button:nth-child(-n + 2)) {
			display: none;
		}
	}
</style>
