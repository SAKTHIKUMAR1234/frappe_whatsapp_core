import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig(({ mode }) => {
	const env = loadEnv(mode, process.cwd(), '')
	return {
		plugins: [vue()],
		resolve: {
			alias: {
				'@': path.resolve(process.cwd(), 'src'),
			},
		},
		server: {
			port: 8096,
			proxy: {
				'/api': {
					target: env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
					changeOrigin: true,
				},
				'/assets': {
					target: env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000',
					changeOrigin: true,
				},
			},
		},
		build: {
			outDir: '../frappe_whatsapp_core/public/core_ui',
			emptyOutDir: true,
			target: 'es2018',
		},
	}
})
