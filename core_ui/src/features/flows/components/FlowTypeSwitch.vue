<script setup>
	import { computed } from 'vue'
	import { useRoute, useRouter } from 'vue-router'

	const route = useRoute()
	const router = useRouter()
	const selected = computed(() =>
		route.query.flow_type === 'automation' ? 'automation' : 'meta',
	)

	function select(type) {
		if (type === selected.value) return
		router.push({
			name: 'flows',
			query: type === 'automation' ? { flow_type: 'automation' } : {},
		})
	}
</script>

<template>
	<nav class="flow-type-switch" aria-label="Flow type">
		<button
			type="button"
			:class="{ active: selected === 'meta' }"
			:aria-current="selected === 'meta' ? 'page' : undefined"
			@click="select('meta')"
		>
			<strong>Meta form</strong>
		</button>
		<button
			type="button"
			:class="{ active: selected === 'automation' }"
			:aria-current="selected === 'automation' ? 'page' : undefined"
			@click="select('automation')"
		>
			<strong>Custom automation</strong>
		</button>
	</nav>
</template>

<style scoped>
	.flow-type-switch {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 10px;
		margin-bottom: 16px;
	}

	button {
		display: block;
		padding: 13px 15px;
		border: 1px solid var(--wa-border);
		border-radius: 13px;
		color: var(--wa-text);
		text-align: left;
		background: var(--wa-surface);
		cursor: pointer;
	}

	button.active {
		border-color: var(--wa-primary);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--wa-primary) 16%, transparent);
	}

	@media (max-width: 650px) {
		.flow-type-switch {
			grid-template-columns: 1fr;
		}
	}
</style>
