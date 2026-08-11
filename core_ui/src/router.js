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
		path: '/access-denied',
		name: 'access-denied',
		component: () => import('@/views/AccessDeniedView.vue'),
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
				path: 'automation-flows',
				name: 'automation-flows',
				meta: { module: 'automation-flows' },
				component: () => import('@/features/flows/views/AutomationFlowListView.vue'),
			},
			{
				path: 'automation-flows/:flowName',
				name: 'automation-flow-builder',
				meta: { module: 'automation-flows' },
				component: () => import('@/features/flows/views/AutomationFlowBuilderView.vue'),
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
	history: createWebHashHistory(
		import.meta.env.DEV
			? '/'
			: window.location.pathname.startsWith('/whatsapp_core')
				? '/whatsapp_core/'
				: '/whatsapp/',
	),
	routes,
})

// A user can keep the app open while a new hashed frontend build is deployed.
// In that case Vue's next lazy route import points at a chunk that no longer
// exists. Recover once with a cache-busted full reload instead of leaving the
// current screen frozen on a failed navigation.
router.onError((error) => {
	const message = String(error?.message || error || '')
	if (!/dynamically imported module|failed to fetch|importing a module script/i.test(message))
		return
	const reloadKey = 'whatsapp:asset-reload'
	if (sessionStorage.getItem(reloadKey)) {
		sessionStorage.removeItem(reloadKey)
		return
	}
	sessionStorage.setItem(reloadKey, '1')
	const url = new URL(window.location.href)
	url.searchParams.set('asset-reload', String(Date.now()))
	window.location.replace(url.toString())
})

router.afterEach((_to, _from, failure) => {
	if (!failure) sessionStorage.removeItem('whatsapp:asset-reload')
})

router.beforeEach(async (to) => {
	const session = useSessionStore()
	if (!session.boot) {
		try {
			await session.fetchBoot()
		} catch {
			if (to.name !== 'login')
				return { name: 'login', query: { redirect: to.fullPath, unavailable: '1' } }
		}
	}
	if (!to.meta.public && !session.authenticated) {
		return { name: 'login', query: { redirect: to.fullPath } }
	}
	if (to.name === 'login' && session.authenticated)
		return { name: session.boot?.default_module || 'inbox' }
	if (to.meta.module && !session.boot?.modules?.includes(to.meta.module)) {
		return { name: session.boot?.default_module || 'inbox' }
	}
})

export default router
