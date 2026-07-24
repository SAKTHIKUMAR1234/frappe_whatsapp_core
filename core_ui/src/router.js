import { createRouter, createWebHashHistory } from 'vue-router'
import { useSessionStore } from '@/stores/session'

const routes = [
	{
		path: '/login',
		name: 'login',
		component: () => import('@/views/LoginView.vue'),
		meta: { public: true },
	},
	{
		path: '/',
		component: () => import('@/layouts/AppShell.vue'),
		children: [
			{
				path: '',
				name: 'dashboard',
				component: () => import('@/features/dashboard/views/DashboardView.vue'),
			},
			{
				path: 'templates',
				name: 'templates',
				component: () => import('@/features/workspaces/views/TemplateCatalogView.vue'),
			},
			{
				path: 'campaigns',
				name: 'campaigns',
				component: () => import('@/features/workspaces/views/BulkMessagingView.vue'),
			},
			{
				path: 'ai-queue',
				name: 'ai-queue',
				component: () => import('@/features/workspaces/views/AIQueueView.vue'),
			},
			{
				path: 'polls',
				name: 'polls',
				component: () => import('@/features/workspaces/views/PollsView.vue'),
			},
			{
				path: 'flows',
				name: 'flows',
				component: () => import('@/features/flows/views/FlowListView.vue'),
			},
			{
				path: 'flows/:flowName',
				name: 'flow-builder',
				component: () => import('@/features/flows/views/FlowBuilderView.vue'),
			},
			{
				path: 'connectors',
				name: 'connectors',
				component: () => import('@/features/workspaces/views/ConnectorsView.vue'),
			},
			{
				path: 'health',
				name: 'health',
				component: () => import('@/features/workspaces/views/HealthView.vue'),
			},
			{
				path: 'settings',
				name: 'settings',
				component: () => import('@/features/workspaces/views/SettingsView.vue'),
			},
		],
	},
]

const router = createRouter({
	history: createWebHashHistory(import.meta.env.DEV ? '/' : '/whatsapp_core'),
	routes,
})

router.beforeEach(async (to) => {
	const session = useSessionStore()
	if (!session.boot) await session.fetchBoot()
	if (!to.meta.public && !session.authenticated) {
		return { name: 'login', query: { redirect: to.fullPath } }
	}
	if (to.name === 'login' && session.authenticated) return { name: 'dashboard' }
})

export default router
