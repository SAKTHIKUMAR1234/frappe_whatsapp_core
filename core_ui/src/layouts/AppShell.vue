<script setup>
	import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import AppDialog from '@/components/AppDialog.vue'
	import InputText from 'primevue/inputtext'
	import Menu from 'primevue/menu'
	import {
		Bell,
		ChevronDown,
		Menu as MenuIcon,
		Search,
		Sparkles,
		ArrowRight,
		Moon,
		Sun,
	} from 'lucide-vue-next'
	import { navigation } from '@/config/navigation'
	import { useSessionStore } from '@/stores/session'
	import { subscribeConnection } from '@/services/realtime'
	import { onAuthExpired } from '@/services/frappe'

	const session = useSessionStore()
	const route = useRoute()
	const router = useRouter()
	const profileMenu = ref()
	const mobileOpen = ref(false)
	const sidebarExpanded = ref(false)
	const commandOpen = ref(false)
	const commandQuery = ref('')
	const commandInput = ref()
	const realtimeStatus = ref('connecting')
	const darkMode = ref(false)
	let unsubscribeConnection = () => {}
	let unsubscribeAuth = () => {}
	let sidebarCollapseTimer = null
	const flushContent = computed(() =>
		['inbox', 'flow-builder'].includes(String(route.name || '')),
	)
	const inboxRoute = computed(() => String(route.name || '') === 'inbox')
	const primaryRole = computed(
		() => session.user?.roles?.find((role) => role.startsWith('WhatsApp ')) || 'Core user',
	)
	const visibleNavigation = computed(() => {
		const modules = new Set(session.boot?.modules || [])
		return navigation
			.map((group) => ({
				...group,
				items: group.items.filter((item) => modules.has(item.module)),
			}))
			.filter((group) => group.items.length)
	})
	const commands = computed(() =>
		visibleNavigation.value.flatMap((group) =>
			group.items.map((item) => ({ ...item, group: group.label })),
		),
	)
	const filteredCommands = computed(() => {
		const query = commandQuery.value.trim().toLowerCase()
		if (!query) return commands.value
		return commands.value.filter((item) =>
			`${item.label} ${item.group}`.toLowerCase().includes(query),
		)
	})

	const initials = computed(() =>
		(session.user?.full_name || 'U')
			.split(' ')
			.slice(0, 2)
			.map((part) => part[0])
			.join('')
			.toUpperCase(),
	)

	const profileItems = [
		{
			label: 'My Frappe profile',
			icon: 'pi pi-user',
			command: () => {
				window.location.href = `/app/user/${encodeURIComponent(session.user?.name || '')}`
			},
		},
		{ separator: true },
		{
			label: 'Sign out',
			icon: 'pi pi-sign-out',
			command: async () => {
				await session.logout()
				router.push({ name: 'login' })
			},
		},
	]

	function openCommand() {
		commandQuery.value = ''
		commandOpen.value = true
		nextTick(() => commandInput.value?.$el?.focus())
	}

	function runCommand(item) {
		commandOpen.value = false
		router.push({ name: item.route })
	}

	function handleShortcut(event) {
		if (event.key === 'Escape' && mobileOpen.value) {
			mobileOpen.value = false
			return
		}
		if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
			event.preventDefault()
			openCommand()
		}
	}

	function expandSidebar() {
		window.clearTimeout(sidebarCollapseTimer)
		sidebarCollapseTimer = null
		sidebarExpanded.value = true
	}

	function collapseSidebarSoon() {
		window.clearTimeout(sidebarCollapseTimer)
		sidebarCollapseTimer = window.setTimeout(() => {
			sidebarCollapseTimer = null
			sidebarExpanded.value = false
		}, 120)
	}

	function handleSidebarFocusOut(event) {
		if (event.currentTarget?.contains(event.relatedTarget)) return
		collapseSidebarSoon()
	}

	function applyTheme(value, persist = true) {
		darkMode.value = Boolean(value)
		document.documentElement.classList.toggle('app-dark', darkMode.value)
		if (persist) localStorage.setItem('whatsapp:theme', darkMode.value ? 'dark' : 'light')
	}

	function toggleTheme() {
		applyTheme(!darkMode.value)
	}

	watch(
		() => route.fullPath,
		() => {
			mobileOpen.value = false
		},
	)
	watch(mobileOpen, (open) => {
		document.documentElement.classList.toggle('mobile-navigation-open', open)
	})

	onMounted(() => {
		const savedTheme = localStorage.getItem('whatsapp:theme')
		applyTheme(
			savedTheme
				? savedTheme === 'dark'
				: window.matchMedia('(prefers-color-scheme: dark)').matches,
			false,
		)
		window.addEventListener('keydown', handleShortcut)
		unsubscribeConnection = subscribeConnection(session.boot?.site, (status) => {
			realtimeStatus.value = status
		})
		unsubscribeAuth = onAuthExpired(() => {
			session.expire()
			router.replace({ name: 'login', query: { redirect: route.fullPath, expired: '1' } })
		})
	})
	onUnmounted(() => {
		document.documentElement.classList.remove('mobile-navigation-open')
		window.clearTimeout(sidebarCollapseTimer)
		window.removeEventListener('keydown', handleShortcut)
		unsubscribeConnection()
		unsubscribeAuth()
	})
</script>

<template>
	<div class="app-shell">
		<Button
			v-if="mobileOpen"
			unstyled
			class="sidebar-scrim"
			aria-label="Close navigation"
			@click="mobileOpen = false"
		/>
		<aside
			id="workspace-navigation"
			:class="['sidebar', { open: mobileOpen, expanded: sidebarExpanded || mobileOpen }]"
			@mouseenter="expandSidebar"
			@mouseleave="collapseSidebarSoon"
			@focusin="expandSidebar"
			@focusout="handleSidebarFocusOut"
		>
			<div class="brand">
				<div class="brand-mark"><Sparkles :size="19" /></div>
				<div>
					<strong>WhatsApp Core</strong>
					<span>Messaging workspace</span>
				</div>
			</div>

			<nav>
				<section v-for="group in visibleNavigation" :key="group.label" class="nav-group">
					<div class="nav-label">{{ group.label }}</div>
					<RouterLink
						v-for="item in group.items"
						:key="`${group.label}-${item.label}`"
						:to="{ name: item.route }"
						:class="['nav-item', { active: route.name === item.route }]"
						:title="item.label"
						:aria-label="item.label"
						@click="mobileOpen = false"
					>
						<component :is="item.icon" :size="18" />
						<span>{{ item.label }}</span>
						<em v-if="item.badge">{{ item.badge }}</em>
					</RouterLink>
				</section>
			</nav>

			<div class="sidebar-footer">
				<div>
					<span :class="['status-dot', realtimeStatus]"></span
					><strong>Realtime {{ realtimeStatus }}</strong>
				</div>
			</div>
		</aside>

		<div :class="['main-shell', { 'inbox-shell': inboxRoute }]">
			<header class="topbar">
				<Button
					class="mobile-menu"
					text
					rounded
					aria-controls="workspace-navigation"
					:aria-expanded="mobileOpen"
					:aria-label="mobileOpen ? 'Close navigation' : 'Open navigation'"
					@click="mobileOpen = !mobileOpen"
				>
					<MenuIcon :size="21" />
				</Button>
				<Button unstyled class="global-search" type="button" @click="openCommand">
					<Search :size="18" />
					<span>Search workspace and jump to a feature…</span>
					<kbd>Ctrl K</kbd>
				</Button>
				<div class="top-actions">
					<Button
						v-if="session.boot?.modules?.includes('inbox')"
						text
						rounded
						severity="secondary"
						:aria-label="darkMode ? 'Use light theme' : 'Use dark theme'"
						@click="toggleTheme"
					>
						<Sun v-if="darkMode" :size="18" />
						<Moon v-else :size="18" />
					</Button>
					<Button
						class="mobile-search-button"
						text
						rounded
						severity="secondary"
						aria-label="Search workspace"
						@click="openCommand"
						><Search :size="19"
					/></Button>
					<Button
						text
						rounded
						severity="secondary"
						aria-label="Open shared inbox"
						@click="router.push({ name: 'inbox' })"
						><Bell :size="19"
					/></Button>
					<Button
						unstyled
						class="profile"
						type="button"
						aria-label="Open user menu"
						@click="profileMenu.toggle($event)"
					>
						<span>{{ initials }}</span>
						<div>
							<strong>{{ session.user?.full_name }}</strong>
							<small>{{ primaryRole }}</small>
						</div>
						<ChevronDown :size="15" />
					</Button>
					<Menu ref="profileMenu" :model="profileItems" popup />
				</div>
			</header>

			<main :class="['content', { flush: flushContent }]"><RouterView /></main>
		</div>
		<AppDialog
			v-model:visible="commandOpen"
			modal
			header="Go to"
			:style="{ width: '560px', maxWidth: '94vw' }"
			class="command-dialog"
		>
			<div class="command-search">
				<Search :size="18" />
				<InputText
					ref="commandInput"
					v-model="commandQuery"
					placeholder="Search inbox, campaigns, flows…"
					fluid
					@keyup.enter="filteredCommands[0] && runCommand(filteredCommands[0])"
				/>
			</div>
			<div class="command-results">
				<Button
					v-for="item in filteredCommands"
					:key="item.route"
					unstyled
					type="button"
					@click="runCommand(item)"
				>
					<span><component :is="item.icon" :size="18" /></span>
					<div>
						<strong>{{ item.label }}</strong
						><small>{{ item.group }}</small>
					</div>
					<ArrowRight :size="16" />
				</Button>
				<div v-if="!filteredCommands.length" class="command-empty">
					No workspace feature matches “{{ commandQuery }}”.
				</div>
			</div>
		</AppDialog>
	</div>
</template>

<style scoped>
	.app-shell {
		width: 100vw;
		height: 100dvh;
		display: flex;
		overflow: hidden;
	}
	.sidebar {
		position: fixed;
		inset: 0 auto 0 0;
		width: 64px;
		padding: 14px 8px 12px;
		display: flex;
		flex-direction: column;
		background: var(--wa-sidebar);
		color: var(--wa-text);
		border-right: 1px solid var(--wa-border);
		z-index: 30;
		overflow: hidden;
		box-shadow: 8px 0 28px rgb(15 23 42 / 2%);
		transition:
			width 280ms cubic-bezier(0.22, 1, 0.36, 1),
			box-shadow 280ms ease;
	}
	.sidebar.expanded {
		width: 236px;
		box-shadow: 14px 0 36px rgb(15 23 42 / 10%);
	}
	.sidebar-scrim {
		display: none;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 11px;
		padding: 0 5px 14px;
	}
	.brand-mark {
		display: grid;
		place-items: center;
		width: 38px;
		height: 38px;
		border-radius: 8px;
		color: white;
		background: var(--wa-green);
		flex: 0 0 38px;
	}
	.brand > div:last-child,
	.nav-item > span,
	.nav-item > em,
	.sidebar-footer strong {
		min-width: 0;
		max-width: 0;
		overflow: hidden;
		opacity: 0;
		white-space: nowrap;
		pointer-events: none;
		transform: translateX(-5px);
		transition:
			opacity 180ms ease 30ms,
			max-width 220ms cubic-bezier(0.22, 1, 0.36, 1),
			transform 220ms cubic-bezier(0.22, 1, 0.36, 1) 30ms;
	}
	.sidebar.expanded .brand > div:last-child,
	.sidebar.expanded .nav-item > span,
	.sidebar.expanded .nav-item > em,
	.sidebar.expanded .sidebar-footer strong {
		max-width: 180px;
		opacity: 1;
		pointer-events: auto;
		transform: translateX(0);
	}
	.brand strong,
	.brand span {
		display: block;
	}
	.brand strong {
		color: var(--wa-text);
		font-size: 15px;
	}
	.brand span {
		color: var(--wa-muted);
		font-size: 11px;
		margin-top: 2px;
	}
	.sidebar nav {
		min-height: 0;
		padding: 6px 0 10px;
		overflow-y: auto;
		overflow-x: hidden;
		scrollbar-gutter: stable;
	}
	.sidebar:not(.expanded) nav {
		scrollbar-width: none;
	}
	.sidebar:not(.expanded) nav::-webkit-scrollbar {
		width: 0;
		height: 0;
	}
	.sidebar:not(.expanded) .nav-item > em {
		display: none;
	}
	.nav-group {
		margin-bottom: 5px;
	}
	.sidebar.expanded .nav-group {
		margin-bottom: 19px;
	}
	.nav-label {
		height: 0;
		padding: 0;
		overflow: hidden;
		opacity: 0;
		color: var(--wa-muted);
		text-transform: uppercase;
		letter-spacing: 0.12em;
		font-size: 12px;
		font-weight: 800;
		white-space: nowrap;
		transition:
			height 220ms cubic-bezier(0.22, 1, 0.36, 1),
			opacity 160ms ease,
			padding 220ms cubic-bezier(0.22, 1, 0.36, 1);
	}
	.sidebar.expanded .nav-label {
		height: 23px;
		padding: 0 11px 7px;
		opacity: 1;
	}
	.nav-item {
		width: 48px;
		height: 38px;
		padding: 0;
		margin: 2px 0;
		display: flex;
		justify-content: center;
		gap: 0;
		align-items: center;
		border-radius: 6px;
		color: var(--wa-text);
		font-size: 13px;
		font-weight: 600;
		transition:
			width 220ms cubic-bezier(0.22, 1, 0.36, 1),
			padding 220ms cubic-bezier(0.22, 1, 0.36, 1),
			gap 220ms cubic-bezier(0.22, 1, 0.36, 1),
			background-color 0.18s ease,
			color 0.18s ease;
	}
	.sidebar.expanded .nav-item {
		width: 100%;
		padding: 0 11px;
		justify-content: flex-start;
		gap: 11px;
	}
	.nav-item > svg {
		flex: 0 0 18px;
	}
	.nav-item:hover {
		color: var(--wa-text);
		background: var(--wa-surface-muted);
	}
	.nav-item.active {
		color: var(--wa-primary);
		background: var(--wa-primary-soft);
	}
	.nav-item em {
		margin-left: auto;
		padding: 2px 6px;
		border-radius: 20px;
		color: var(--wa-success);
		background: var(--wa-success-soft);
		font-size: 12px;
		font-style: normal;
		text-transform: uppercase;
	}
	.sidebar-footer {
		margin-top: auto;
		padding: 13px 8px;
		border-top: 1px solid var(--wa-border);
	}
	.sidebar-footer div {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 9px;
	}
	.sidebar.expanded .sidebar-footer div {
		justify-content: flex-start;
	}
	.sidebar-footer strong {
		color: var(--wa-text);
		font-size: 11px;
	}
	.main-shell {
		min-width: 0;
		width: calc(100vw - 64px);
		height: 100dvh;
		margin-left: 64px;
		overflow: hidden;
	}
	.topbar {
		position: sticky;
		top: 0;
		z-index: 20;
		height: 56px;
		padding: 0 20px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		background: color-mix(in srgb, var(--wa-surface) 94%, transparent);
		border-bottom: 1px solid var(--wa-border);
		backdrop-filter: blur(16px);
	}
	.global-search {
		width: min(490px, 48vw);
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 9px 12px;
		border: 1px solid var(--wa-border);
		border-radius: 6px;
		color: var(--wa-muted);
		background: var(--wa-surface-muted);
		cursor: pointer;
		text-align: left;
	}
	.global-search span {
		flex: 1;
		color: var(--wa-muted);
		font-size: 13px;
	}
	.global-search kbd {
		padding: 2px 6px;
		border: 1px solid var(--wa-border-soft);
		border-radius: 5px;
		background: var(--wa-surface);
		color: var(--wa-muted);
		font-size: 12px;
	}
	.command-search {
		position: relative;
		display: flex;
		align-items: center;
	}
	.command-search > svg {
		position: absolute;
		left: 13px;
		z-index: 1;
		color: var(--wa-muted);
	}
	.command-search :deep(input) {
		padding-left: 41px;
	}
	.command-results {
		max-height: min(440px, 60dvh);
		margin-top: 12px;
		display: grid;
		gap: 4px;
		overflow-y: auto;
	}
	.command-results button {
		width: 100%;
		padding: 10px;
		display: grid;
		grid-template-columns: 38px 1fr 20px;
		gap: 11px;
		align-items: center;
		border: 0;
		border-radius: 10px;
		background: transparent;
		color: var(--wa-text);
		text-align: left;
		cursor: pointer;
	}
	.command-results button:hover,
	.command-results button:focus-visible {
		background: var(--wa-mint);
		outline: 0;
	}
	.command-results button > span {
		width: 38px;
		height: 38px;
		display: grid;
		place-items: center;
		border-radius: 10px;
		color: var(--wa-primary);
		background: var(--wa-surface);
		border: 1px solid var(--wa-border);
	}
	.command-results button div {
		display: grid;
		gap: 2px;
	}
	.command-results button strong {
		font-size: 13px;
	}
	.command-results button small,
	.command-empty {
		color: var(--wa-muted);
		font-size: 11px;
	}
	.command-empty {
		padding: 28px 12px;
		text-align: center;
	}
	.top-actions {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.profile {
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 5px 7px;
		border: 0;
		background: transparent;
		cursor: pointer;
	}
	.profile > span {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 10px;
		background: var(--wa-primary-soft);
		color: var(--wa-primary);
		font-size: 12px;
		font-weight: 800;
	}
	.profile div {
		text-align: left;
	}
	.profile strong,
	.profile small {
		display: block;
	}
	.profile strong {
		font-size: 11px;
	}
	.profile small {
		color: var(--wa-muted);
		font-size: 12px;
		margin-top: 2px;
	}
	.content {
		min-width: 0;
		width: 100%;
		height: calc(100dvh - 56px);
		padding: 24px clamp(20px, 2vw, 32px) 32px;
		overflow: auto;
	}
	.content.flush {
		padding: 0;
	}
	@media (min-width: 901px) {
		.inbox-shell .topbar {
			display: none;
		}
		.inbox-shell .content {
			height: 100dvh;
		}
	}
	.mobile-menu {
		display: none;
	}
	.mobile-search-button {
		display: none;
	}
	:global(html.mobile-navigation-open) {
		overflow: hidden;
	}
	@media (max-width: 900px) {
		.sidebar {
			width: min(88vw, 300px);
			transform: translateX(-100%);
			visibility: hidden;
			pointer-events: none;
			transition:
				transform 0.2s ease,
				visibility 0s linear 0.2s;
		}
		.sidebar.open {
			transform: translateX(0);
			visibility: visible;
			pointer-events: auto;
			transition-delay: 0s;
		}
		.sidebar-scrim {
			position: fixed;
			inset: 0;
			display: block;
			border: 0;
			background: rgb(7 28 22 / 48%);
			backdrop-filter: blur(2px);
			z-index: 29;
		}
		.main-shell {
			width: 100vw;
			margin-left: 0;
		}
		.mobile-menu {
			display: inline-flex;
		}
		.mobile-search-button {
			display: inline-flex;
		}
		.global-search {
			display: none;
		}
		.content {
			padding: 18px;
		}
		.content.flush {
			padding: 0;
		}
		.profile div {
			display: none;
		}
	}
	@media (max-width: 520px) {
		.topbar {
			height: 56px;
			padding: 0 10px;
		}
		.content {
			padding: 12px;
		}
		.content.flush {
			padding: 0;
		}
		.top-actions {
			gap: 2px;
		}
	}
</style>
