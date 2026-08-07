<script setup>
	import { onMounted, onUnmounted } from 'vue'
	import Toast from 'primevue/toast'
	import ConfirmDialog from 'primevue/confirmdialog'
	import { useToast } from 'primevue/usetoast'
	import AppErrorBoundary from '@/components/AppErrorBoundary.vue'
	import { onApiFailure } from '@/services/frappe'

	const toast = useToast()
	let unsubscribe = () => {}
	let lastFailure = { message: '', at: 0 }

	onMounted(() => {
		unsubscribe = onApiFailure((event) => {
			const detail = event.detail || {}
			const now = Date.now()
			if (lastFailure.message === detail.message && now - lastFailure.at < 1500) return
			lastFailure = { message: detail.message, at: now }
			toast.add({
				severity: 'error',
				summary: detail.status ? 'Service unavailable' : 'Connection lost',
				detail: detail.message,
				life: 6000,
			})
		})
	})
	onUnmounted(() => unsubscribe())
</script>

<template>
	<Toast position="bottom-right" />
	<ConfirmDialog />
	<AppErrorBoundary><RouterView /></AppErrorBoundary>
</template>
