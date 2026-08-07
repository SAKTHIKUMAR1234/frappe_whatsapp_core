<script setup>
	import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Dialog from 'primevue/dialog'
	import InputText from 'primevue/inputtext'
	import Menu from 'primevue/menu'
	import {
		Bell,
		ChevronDown,
		Menu as MenuIcon,
		Search,
		Sparkles,
		ArrowRight,
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
	const commandOpen = ref(false)
	const commandQuery = ref('')
	const commandInput = ref()
	const realtimeStatus = ref('connecting')
	let unsubscribeConnection = () => {}
	let unsubscribeAuth = () => {}
	const tenantLabel = computed(() => session.boot?.site || 'Current Frappe site')
	const primaryRole = computed(
		() => session.user?.roles?.find((role) => role.startsWith('WhatsApp ')) || 'Site user',
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
		if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
			event.preventDefault()
			openCommand()
		}
	}

	onMounted(() => {
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
		window.removeEventListener('keydown', handleShortcut)
		unsubscribeConnection()
		unsubscribeAuth()
	})
</script>

<template>
	<div class="app-shell">
		<button
			v-if="mobileOpen"
			class="sidebar-scrim"
			aria-label="Close navigation"
			@click="mobileOpen = false"
		/>
		<aside :class="['sidebar', { open: mobileOpen }]">
			<div class="brand">
				<div class="brand-mark"><Sparkles :size="19" /></div>
				<div>
					<strong>WhatsApp Core</strong>
					<span>Company workspace</span>
				</div>
			</div>

			<div class="tenant-card">
				<div class="tenant-avatar">WA</div>
				<div>
					<span>Current site</span>
					<strong>{{ tenantLabel }}</strong>
				</div>
				<ChevronDown :size="15" />
			</div>

			<nav>
				<section v-for="group in visibleNavigation" :key="group.label" class="nav-group">
					<div class="nav-label">{{ group.label }}</div>
					<RouterLink
						v-for="item in group.items"
						:key="`${group.label}-${item.label}`"
						:to="{ name: item.route }"
						:class="['nav-item', { active: route.name === item.route }]"
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
				<small>{{ session.boot?.site }}</small>
			</div>
		</aside>

		<div class="main-shell">
			<header class="topbar">
				<Button class="mobile-menu" text rounded @click="mobileOpen = !mobileOpen">
					<MenuIcon :size="21" />
				</Button>
				<button class="global-search" type="button" @click="openCommand">
					<Search :size="18" />
					<span>Search workspace and jump to a feature…</span>
					<kbd>Ctrl K</kbd>
				</button>
				<div class="top-actions">
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
					<button class="profile" @click="profileMenu.toggle($event)">
						<span>{{ initials }}</span>
						<div>
							<strong>{{ session.user?.full_name }}</strong>
							<small>{{ primaryRole }}</small>
						</div>
						<ChevronDown :size="15" />
					</button>
					<Menu ref="profileMenu" :model="profileItems" popup />
				</div>
			</header>

			<main class="content"><RouterView /></main>
		</div>
		<Dialog
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
					placeholder="Search inbox, campaigns, flows, settings…"
					fluid
					@keyup.enter="filteredCommands[0] && runCommand(filteredCommands[0])"
				/>
			</div>
			<div class="command-results">
				<button
					v-for="item in filteredCommands"
					:key="item.route"
					type="button"
					@click="runCommand(item)"
				>
					<span><component :is="item.icon" :size="18" /></span>
					<div>
						<strong>{{ item.label }}</strong
						><small>{{ item.group }}</small>
					</div>
					<ArrowRight :size="16" />
				</button>
				<div v-if="!filteredCommands.length" class="command-empty">
					No workspace feature matches “{{ commandQuery }}”.
				</div>
			</div>
		</Dialog>
	</div>
</template>

<style scoped>
	.app-shell {
		min-height: 100vh;
		display: flex;
	}
	.sidebar {
		position: fixed;
		inset: 0 auto 0 0;
		width: 272px;
		padding: 22px 16px 16px;
		display: flex;
		flex-direction: column;
		background: var(--wa-sidebar);
		color: #dce9e3;
		z-index: 30;
		overflow-y: auto;
	}
	.sidebar-scrim {
		display: none;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 11px;
		padding: 0 8px 20px;
	}
	.brand-mark {
		display: grid;
		place-items: center;
		width: 38px;
		height: 38px;
		border-radius: 12px;
		color: #082c21;
		background: linear-gradient(135deg, #75f0c2, #27b681);
	}
	.brand strong,
	.brand span {
		display: block;
	}
	.brand strong {
		color: white;
		font-size: 15px;
	}
	.brand span {
		color: #8ca89d;
		font-size: 11px;
		margin-top: 2px;
	}
	.tenant-card {
		display: grid;
		grid-template-columns: 36px 1fr 18px;
		gap: 10px;
		align-items: center;
		padding: 11px;
		margin-bottom: 20px;
		border: 1px solid #294238;
		border-radius: 13px;
		background: #173128;
	}
	.tenant-avatar {
		display: grid;
		place-items: center;
		height: 36px;
		border-radius: 10px;
		background: #d9fbe9;
		color: #075e54;
		font-size: 11px;
		font-weight: 800;
	}
	.tenant-card span,
	.tenant-card strong {
		display: block;
	}
	.tenant-card span {
		color: #8ca89d;
		font-size: 10px;
	}
	.tenant-card strong {
		color: white;
		font-size: 13px;
		margin-top: 2px;
	}
	.nav-group {
		margin-bottom: 19px;
	}
	.nav-label {
		padding: 0 11px 7px;
		color: #718e82;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		font-size: 10px;
		font-weight: 800;
	}
	.nav-item {
		height: 38px;
		padding: 0 11px;
		margin: 2px 0;
		display: flex;
		gap: 11px;
		align-items: center;
		border-radius: 10px;
		color: #a9beb5;
		font-size: 13px;
		font-weight: 600;
		transition: 0.18s;
	}
	.nav-item:hover {
		color: white;
		background: #1b392e;
	}
	.nav-item.active {
		color: white;
		background: #075e54;
	}
	.nav-item em {
		margin-left: auto;
		padding: 2px 6px;
		border-radius: 20px;
		color: #0b3a2b;
		background: #74e8ba;
		font-size: 9px;
		font-style: normal;
		text-transform: uppercase;
	}
	.sidebar-footer {
		margin-top: auto;
		padding: 13px 11px;
		border-top: 1px solid #294238;
	}
	.sidebar-footer div {
		display: flex;
		align-items: center;
		gap: 9px;
	}
	.sidebar-footer strong {
		color: #d8e8e1;
		font-size: 11px;
	}
	.sidebar-footer small {
		display: block;
		margin-top: 7px;
		color: #6f8f82;
		font-size: 10px;
	}
	.main-shell {
		min-width: 0;
		width: 100%;
		margin-left: 272px;
	}
	.topbar {
		position: sticky;
		top: 0;
		z-index: 20;
		height: 68px;
		padding: 0 30px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		background: rgba(255, 255, 255, 0.92);
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
		border-radius: 12px;
		color: #839089;
		background: #f7f9f8;
		cursor: pointer;
		text-align: left;
	}
	.global-search span {
		flex: 1;
		color: #6f7f77;
		font-size: 13px;
	}
	.global-search kbd {
		padding: 2px 6px;
		border: 1px solid #dce4e0;
		border-radius: 5px;
		background: white;
		color: #7b8882;
		font-size: 10px;
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
		background: white;
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
		background: #dff8ec;
		color: #075e54;
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
		color: #84918b;
		font-size: 10px;
		margin-top: 2px;
	}
	.content {
		padding: 28px 30px;
		max-width: 1600px;
		margin: 0 auto;
	}
	.mobile-menu {
		display: none;
	}
	.mobile-search-button {
		display: none;
	}
	@media (max-width: 900px) {
		.sidebar {
			width: min(88vw, 300px);
			transform: translateX(-100%);
			transition: 0.2s;
		}
		.sidebar.open {
			transform: translateX(0);
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
		.profile div {
			display: none;
		}
	}
	@media (max-width: 520px) {
		.topbar {
			height: 60px;
			padding: 0 10px;
		}
		.content {
			padding: 12px;
		}
		.top-actions {
			gap: 2px;
		}
	}
</style>
