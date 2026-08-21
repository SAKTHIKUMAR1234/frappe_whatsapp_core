import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { call, logout as logoutRequest } from '@/services/frappe'

export const useSessionStore = defineStore('core-session', () => {
	const boot = ref(null)
	const loading = ref(false)
	const bootError = ref('')
	const authenticated = computed(() => Boolean(boot.value?.authenticated))
	const user = computed(() => boot.value?.user || null)

	async function fetchBoot() {
		loading.value = true
		bootError.value = ''
		try {
			boot.value = await call('frappe_whatsapp_core.frontend_api.bootstrap')
			return boot.value
		} catch (error) {
			boot.value = { authenticated: false }
			bootError.value = error?.message || 'Unable to reach the messaging backend.'
			throw error
		} finally {
			loading.value = false
		}
	}

	async function logout() {
		try {
			await logoutRequest()
		} finally {
			boot.value = { authenticated: false }
		}
	}

	function expire() {
		boot.value = { authenticated: false }
	}

	return {
		boot,
		bootError,
		loading,
		authenticated,
		user,
		fetchBoot,
		logout,
		expire,
	}
})
