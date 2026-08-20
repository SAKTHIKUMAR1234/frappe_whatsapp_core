<script setup>
	defineProps({
		size: { type: [Number, String], default: 32 },
	})
</script>

<template>
	<svg
		class="core-mark"
		viewBox="0 0 64 64"
		:width="size"
		:height="size"
		aria-hidden="true"
		focusable="false"
	>
		<rect width="64" height="64" rx="17" fill="#087c72" />
		<path
			d="M15 15h28c5 0 9 4 9 9v13c0 5-4 9-9 9H29l-11 7 3-7h-6c-5 0-9-4-9-9V24c0-5 4-9 9-9Z"
			fill="#f4fffb"
		/>
		<path d="M45 22h4c5 0 9 4 9 9v8c0 4-3 8-7 9l2 5-9-6" fill="#53e2b4" />
		<path d="M21 31h20M31 24v14" stroke="#087c72" stroke-width="3" stroke-linecap="round" />
		<circle cx="21" cy="31" r="4" fill="#16b692" />
		<circle cx="41" cy="31" r="4" fill="#16b692" />
		<circle cx="31" cy="24" r="4" fill="#087c72" />
		<circle cx="31" cy="38" r="4" fill="#087c72" />
	</svg>
</template>

<style scoped>
	.core-mark {
		display: block;
		flex: 0 0 auto;
	}
</style>
