import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { call, login as loginRequest, logout as logoutRequest } from '@/services/frappe'

export const useSessionStore = defineStore('core-session', () => {
	const boot = ref(null)
	const loading = ref(false)
	const authenticated = computed(() => Boolean(boot.value?.authenticated))
	const user = computed(() => boot.value?.user || null)

	async function fetchBoot() {
		loading.value = true
		try {
			boot.value = await call('frappe_whatsapp_core.frontend_api.bootstrap')
			return boot.value
		} finally {
			loading.value = false
		}
	}

	async function login(email, password) {
		await loginRequest(email, password)
		return fetchBoot()
	}

	async function logout() {
		await logoutRequest()
		boot.value = { authenticated: false }
	}

	return { boot, loading, authenticated, user, fetchBoot, login, logout }
})
