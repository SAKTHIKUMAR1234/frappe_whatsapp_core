import {
	Activity,
	Bot,
	GitBranch,
	PhoneCall,
	MessagesSquare,
	LayoutDashboard,
	Megaphone,
	MessageCircleMore,
	MessageSquareText,
	PlugZap,
	Settings,
	ShieldCheck,
	UsersRound,
} from 'lucide-vue-next'

export const navigation = [
	{
		label: 'Workspace',
		items: [
			{ label: 'Shared Inbox', route: 'inbox', icon: MessageCircleMore, badge: 'Live' },
			{ label: 'Overview', route: 'dashboard', icon: LayoutDashboard },
		],
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
			{ label: 'Forms & Surveys', route: 'polls', icon: Activity },
			{ label: 'Groups', route: 'groups', icon: MessagesSquare },
			{ label: 'Calling', route: 'calling', icon: PhoneCall },
		],
	},
	{
		label: 'Automate',
		items: [
			{ label: 'Meta Flow Builder', route: 'flows', icon: GitBranch },
			{ label: 'Connectors', route: 'connectors', icon: PlugZap },
		],
	},
	{
		label: 'Administration',
		items: [
			{ label: 'Teams', route: 'teams', icon: UsersRound },
			{ label: 'Audit & Health', route: 'health', icon: ShieldCheck },
			{ label: 'Company Settings', route: 'settings', icon: Settings },
		],
	},
]
