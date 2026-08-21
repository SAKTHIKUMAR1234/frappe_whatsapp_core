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
		<rect x="1" y="1" width="62" height="62" rx="7" fill="#121517" stroke="#394047" />
		<path
			d="M20 20h24c3.3 0 6 2.7 6 6v12c0 3.3-2.7 6-6 6H31l-9 6 2.2-6H20c-3.3 0-6-2.7-6-6V26c0-3.3 2.7-6 6-6Z"
			fill="#eaeef4"
		/>
		<ellipse
			cx="32"
			cy="32"
			rx="24"
			ry="9"
			fill="none"
			stroke="#3fb6de"
			stroke-width="2"
			transform="rotate(-25 32 32)"
		/>
		<ellipse
			cx="32"
			cy="32"
			rx="24"
			ry="9"
			fill="none"
			stroke="#3fb6de"
			stroke-width="1.5"
			opacity=".65"
			transform="rotate(55 32 32)"
		/>
		<circle cx="50" cy="18" r="3" fill="#65c8e8" />
		<path d="M24 32h16M32 25v14" stroke="#087fa8" stroke-width="3" stroke-linecap="square" />
		<circle cx="32" cy="32" r="3.5" fill="#3fb6de" />
	</svg>
</template>

<style scoped>
	.core-mark {
		display: block;
		flex: 0 0 auto;
	}
</style>
