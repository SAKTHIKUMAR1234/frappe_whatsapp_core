import {
	Activity,
	Bot,
	PhoneCall,
	MessagesSquare,
	LayoutDashboard,
	Megaphone,
	MessageCircleMore,
	MessageSquareText,
	ShieldCheck,
	UsersRound,
} from 'lucide-vue-next'

export const navigation = [
	{
		label: 'Workspace',
		items: [
			{
				label: 'Shared Inbox',
				route: 'inbox',
				module: 'inbox',
				icon: MessageCircleMore,
				badge: 'Live',
			},
			{ label: 'Overview', route: 'dashboard', module: 'dashboard', icon: LayoutDashboard },
		],
	},
	{
		label: 'Engage',
		items: [
			{
				label: 'Available Templates',
				route: 'templates',
				module: 'templates',
				icon: MessageSquareText,
				readOnly: true,
			},
			{ label: 'Bulk Messaging', route: 'campaigns', module: 'campaigns', icon: Megaphone },
			{ label: 'AI Queue', route: 'ai-queue', module: 'ai-queue', icon: Bot },
			{ label: 'Groups', route: 'groups', module: 'groups', icon: MessagesSquare },
			{ label: 'Calling', route: 'calling', module: 'calling', icon: PhoneCall },
			{ label: 'Flow Builder', route: 'flows', module: 'flows', icon: Activity },
		],
	},
	{
		label: 'Administration',
		items: [
			{ label: 'Teams', route: 'teams', module: 'teams', icon: UsersRound },
			{ label: 'Audit & Health', route: 'health', module: 'health', icon: ShieldCheck },
		],
	},
]
