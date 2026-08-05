<script setup>
	import { computed, ref } from 'vue'
	import { useRoute, useRouter } from 'vue-router'
	import Button from 'primevue/button'
	import Menu from 'primevue/menu'
	import { Bell, ChevronDown, Menu as MenuIcon, Search, Sparkles } from 'lucide-vue-next'
	import { navigation } from '@/config/navigation'
	import { useSessionStore } from '@/stores/session'

	const session = useSessionStore()
	const route = useRoute()
	const router = useRouter()
	const profileMenu = ref()
	const mobileOpen = ref(false)
	const tenantLabel = computed(() => session.boot?.site || 'Current Frappe site')
	const primaryRole = computed(
		() => session.user?.roles?.find((role) => role.startsWith('WhatsApp ')) || 'Site user',
	)
	const visibleNavigation = computed(() => {
		const modules = new Set(session.boot?.modules || [])
		return navigation
			.map((group) => ({ ...group, items: group.items.filter((item) => modules.has(item.module)) }))
			.filter((group) => group.items.length)
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
		{ label: 'My profile', icon: 'pi pi-user' },
		{ label: 'Theme', icon: 'pi pi-moon' },
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
</script>

<template>
	<div class="app-shell">
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
				<div><span class="status-dot"></span><strong>Core UI connected</strong></div>
				<small>{{ session.boot?.site }}</small>
			</div>
		</aside>

		<div class="main-shell">
			<header class="topbar">
				<Button class="mobile-menu" text rounded @click="mobileOpen = !mobileOpen">
					<MenuIcon :size="21" />
				</Button>
				<div class="global-search">
					<Search :size="18" />
					<input placeholder="Search conversations, flows and campaigns..." />
					<kbd>⌘ K</kbd>
				</div>
				<div class="top-actions">
					<Button text rounded severity="secondary"><Bell :size="19" /></Button>
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
		width: 260px;
		padding: 22px 16px 16px;
		display: flex;
		flex-direction: column;
		background: var(--wa-sidebar);
		color: #dce9e3;
		z-index: 30;
		overflow-y: auto;
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
		font-size: 14px;
	}
	.brand span {
		color: #8ca89d;
		font-size: 10px;
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
		font-size: 9px;
	}
	.tenant-card strong {
		color: white;
		font-size: 12px;
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
		font-size: 9px;
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
		font-size: 12px;
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
		font-size: 8px;
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
		font-size: 10px;
	}
	.sidebar-footer small {
		display: block;
		margin-top: 7px;
		color: #6f8f82;
		font-size: 9px;
	}
	.main-shell {
		min-width: 0;
		width: 100%;
		margin-left: 260px;
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
	}
	.global-search input {
		flex: 1;
		border: 0;
		outline: 0;
		background: transparent;
		color: #26332e;
		font-size: 12px;
	}
	.global-search kbd {
		padding: 2px 6px;
		border: 1px solid #dce4e0;
		border-radius: 5px;
		background: white;
		color: #7b8882;
		font-size: 9px;
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
		font-size: 11px;
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
		font-size: 9px;
		margin-top: 2px;
	}
	.content {
		padding: 30px;
		max-width: 1600px;
		margin: 0 auto;
	}
	.mobile-menu {
		display: none;
	}
	@media (max-width: 900px) {
		.sidebar {
			transform: translateX(-100%);
			transition: 0.2s;
		}
		.sidebar.open {
			transform: translateX(0);
		}
		.main-shell {
			margin-left: 0;
		}
		.mobile-menu {
			display: inline-flex;
		}
		.global-search {
			display: none;
		}
		.content {
			padding: 20px;
		}
		.profile div {
			display: none;
		}
	}
</style>
