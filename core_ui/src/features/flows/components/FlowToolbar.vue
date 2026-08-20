<script setup>
	import Button from 'primevue/button'
	import Tag from 'primevue/tag'
	import {
		ArrowLeft,
		CheckCircle2,
		Clock3,
		LayoutDashboard,
		Play,
		Rocket,
		Save,
	} from 'lucide-vue-next'

	defineProps({
		flow: {
			type: Object,
			required: true,
		},
		saving: Boolean,
		validating: Boolean,
		publishing: Boolean,
		requesting: Boolean,
		canManage: Boolean,
	})

	defineEmits([
		'back',
		'open-triggers',
		'arrange',
		'save',
		'validate',
		'publish',
		'request-approval',
	])

	function approvalSeverity(status) {
		if (status === 'Approved') return 'success'
		if (status === 'Rejected') return 'danger'
		if (status === 'Pending Approval') return 'info'
		return 'secondary'
	}
</script>

<template>
	<header class="flow-toolbar">
		<Button text rounded aria-label="Back to flows" @click="$emit('back')">
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
			<Tag
				:value="flow.approval_status || 'Draft'"
				:severity="approvalSeverity(flow.approval_status)"
				rounded
			/>
		</div>

		<div class="toolbar-actions">
			<Button
				label="Arrange"
				severity="secondary"
				outlined
				title="Arrange overlapping steps"
				@click="$emit('arrange')"
			>
				<template #icon><LayoutDashboard :size="15" /></template>
			</Button>
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
			<Button
				v-if="canManage"
				label="Approve & publish"
				:loading="publishing"
				@click="$emit('publish')"
			>
				<template #icon><Rocket :size="15" /></template>
			</Button>
			<Button
				v-else
				:label="
					flow.approval_status === 'Pending Approval'
						? 'Approval pending'
						: 'Request approval'
				"
				:disabled="flow.approval_status === 'Pending Approval'"
				:loading="requesting"
				@click="$emit('request-approval')"
			>
				<template #icon><Clock3 :size="15" /></template>
			</Button>
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
		background: var(--wa-surface);
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
		color: var(--wa-muted);
		font-size: 12px;
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

	@media (max-width: 700px) {
		.toolbar-actions :deep(.p-button) {
			width: 36px;
			height: 36px;
			padding: 0;
		}

		.toolbar-actions :deep(.p-button-label) {
			position: absolute;
			width: 1px;
			height: 1px;
			padding: 0;
			margin: -1px;
			overflow: hidden;
			clip: rect(0, 0, 0, 0);
			white-space: nowrap;
			border: 0;
		}
	}

	@media (max-width: 540px) {
		.flow-toolbar {
			padding: 0 8px;
			gap: 6px;
		}

		.flow-title {
			flex: 1;
			gap: 0;
		}

		.flow-title > div {
			min-width: 0;
		}

		.flow-title strong {
			max-width: 120px;
		}

		.flow-title :deep(.p-tag) {
			display: none;
		}

		.toolbar-actions {
			gap: 2px;
		}

		.toolbar-actions :deep(.p-button) {
			padding: 0;
			font-size: 11px;
		}
	}
</style>
