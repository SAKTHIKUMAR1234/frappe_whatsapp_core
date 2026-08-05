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
				path: 'inbox/:conversation?',
				name: 'inbox',
				meta: { module: 'inbox' },
				component: () => import('@/features/inbox/views/InboxView.vue'),
			},
			{
				path: '',
				name: 'dashboard',
				meta: { module: 'dashboard' },
				component: () => import('@/features/dashboard/views/DashboardView.vue'),
			},
			{
				path: 'templates',
				name: 'templates',
				meta: { module: 'templates' },
				component: () => import('@/features/workspaces/views/TemplateCatalogView.vue'),
			},
			{
				path: 'campaigns',
				name: 'campaigns',
				meta: { module: 'campaigns' },
				component: () => import('@/features/workspaces/views/BulkMessagingView.vue'),
			},
			{
				path: 'ai-queue',
				name: 'ai-queue',
				meta: { module: 'ai-queue' },
				component: () => import('@/features/workspaces/views/AIQueueView.vue'),
			},
			{
				path: 'polls',
				name: 'polls',
				meta: { module: 'polls' },
				component: () => import('@/features/workspaces/views/PollsView.vue'),
			},
			{
				path: 'flows',
				name: 'flows',
				meta: { module: 'flows' },
				component: () => import('@/features/flows/views/FlowListView.vue'),
			},
			{
				path: 'flows/:flowName',
				name: 'flow-builder',
				meta: { module: 'flows' },
				component: () => import('@/features/flows/views/FlowBuilderView.vue'),
			},
			{
				path: 'groups',
				name: 'groups',
				meta: { module: 'groups' },
				component: () => import('@/features/workspaces/views/GroupsView.vue'),
			},
			{
				path: 'calling',
				name: 'calling',
				meta: { module: 'calling' },
				component: () => import('@/features/workspaces/views/CallingView.vue'),
			},
			{
				path: 'connectors',
				name: 'connectors',
				meta: { module: 'connectors' },
				component: () => import('@/features/workspaces/views/ConnectorsView.vue'),
			},
			{
				path: 'teams',
				name: 'teams',
				meta: { module: 'teams' },
				component: () => import('@/features/teams/views/TeamsView.vue'),
			},
			{
				path: 'health',
				name: 'health',
				meta: { module: 'health' },
				component: () => import('@/features/workspaces/views/HealthView.vue'),
			},
			{
				path: 'settings',
				name: 'settings',
				meta: { module: 'settings' },
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
	if (to.name === 'login' && session.authenticated) return { name: session.boot?.default_module || 'inbox' }
	if (to.meta.module && !session.boot?.modules?.includes(to.meta.module)) {
		return { name: session.boot?.default_module || 'inbox' }
	}
})

export default router
