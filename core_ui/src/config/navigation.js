import {
	Activity,
	Bot,
	GitBranch,
	LayoutDashboard,
	Megaphone,
	MessageSquareText,
	PlugZap,
	Settings,
	ShieldCheck,
} from 'lucide-vue-next'

export const navigation = [
	{
		label: 'Workspace',
		items: [{ label: 'Overview', route: 'dashboard', icon: LayoutDashboard }],
	},
	{
		label: 'Engage',
		items: [
			{
				label: 'Available Templates',
				route: 'templates',
				icon: MessageSquareText,
				readOnly: true,
			},
			{ label: 'Bulk Messaging', route: 'campaigns', icon: Megaphone },
			{ label: 'AI Queue', route: 'ai-queue', icon: Bot },
			{ label: 'Polls & Forms', route: 'polls', icon: Activity },
		],
	},
	{
		label: 'Automate',
		items: [
			{ label: 'Flow Builder', route: 'flows', icon: GitBranch },
			{ label: 'Connectors', route: 'connectors', icon: PlugZap },
		],
	},
	{
		label: 'Administration',
		items: [
			{ label: 'Audit & Health', route: 'health', icon: ShieldCheck },
			{ label: 'Company Settings', route: 'settings', icon: Settings },
		],
	},
]
