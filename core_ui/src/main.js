import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import ToastService from 'primevue/toastservice'
import ConfirmationService from 'primevue/confirmationservice'
import Aura from '@primeuix/themes/aura'
import { definePreset } from '@primeuix/themes'

import App from './App.vue'
import router from './router'
import 'primeicons/primeicons.css'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import './styles.css'

const AndrometiqAura = definePreset(Aura, {
	semantic: {
		primary: {
			50: '#eefafe',
			100: '#d6f3fb',
			200: '#ade7f7',
			300: '#78d7ee',
			400: '#3fb6de',
			500: '#159bc7',
			600: '#087fa8',
			700: '#096586',
			800: '#0c536d',
			900: '#0d465b',
			950: '#072e3d',
		},
	},
})

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(PrimeVue, {
	theme: {
		preset: AndrometiqAura,
		options: {
			darkModeSelector: '.app-dark',
			cssLayer: false,
		},
	},
})
app.use(ToastService)
app.use(ConfirmationService)
app.mount('#app')
