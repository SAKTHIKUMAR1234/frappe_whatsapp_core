import {
	Activity,
	Bot,
	Megaphone,
	MessageSquareText,
	PlugZap,
	Settings,
	ShieldCheck,
} from 'lucide-vue-next'

function metrics(...items) {
	return items.map(([label, value, detail]) => ({
		label,
		value,
		detail,
	}))
}

export const templateCatalogDefinition = {
	eyebrow: 'Integration catalog',
	title: 'Available Templates',
	icon: MessageSquareText,
	description: 'Templates assigned and enabled for this site by the Integration app.',
	primaryAction: 'Refresh catalog',
	readOnly: true,
	metrics: metrics(
		['Approved templates', '0', 'Synced from Meta'],
		['Available to flows', '0', 'Assigned to this site'],
		['Disabled', '0', 'Hidden from company actions'],
	),
}

export const bulkMessagingDefinition = {
	eyebrow: 'Engage',
	title: 'Bulk Messaging',
	icon: Megaphone,
	description: 'Create an audience, select an available template and monitor delivery.',
	primaryAction: 'New bulk message',
	metrics: metrics(
		['Drafts', '0', 'Not scheduled'],
		['Scheduled', '0', 'Waiting to send'],
		['Delivered', '0', 'Current period'],
	),
}

export const aiQueueDefinition = {
	eyebrow: 'Assist',
	title: 'AI Queue',
	icon: Bot,
	description: 'Review uncertain classifications and approve suggested actions.',
	primaryAction: 'Configure AI policy',
	metrics: metrics(
		['Needs review', '0', 'Human decision required'],
		['Auto-resolved', '0', 'Current period'],
		['Accuracy', '—', 'No samples yet'],
	),
}

export const pollsDefinition = {
	eyebrow: 'Collect',
	title: 'Polls & Forms',
	icon: Activity,
	description: 'Launch questions from approved templates and store structured answers.',
	primaryAction: 'Create poll',
	metrics: metrics(
		['Drafts', '0', 'Being configured'],
		['Active', '0', 'Collecting answers'],
		['Responses', '0', 'Current period'],
	),
}

export const connectorsDefinition = {
	eyebrow: 'Extend',
	title: 'Connectors',
	icon: PlugZap,
	description: 'Expose typed, allowlisted actions without permitting arbitrary code.',
	primaryAction: 'Add connector',
	metrics: metrics(
		['Connected', '0', 'Healthy integrations'],
		['Actions', '2', 'Registered in Core'],
		['Failures', '0', 'Last 24 hours'],
	),
}

export const healthDefinition = {
	eyebrow: 'Observe',
	title: 'Audit & Health',
	icon: ShieldCheck,
	description: 'Track Core processing, flow execution and integration health for this site.',
	primaryAction: 'Export audit log',
	metrics: metrics(
		['Flow failures', '0', 'Last 24 hours'],
		['Retries', '0', 'Last 24 hours'],
		['Processing', 'Healthy', 'Site-local engine'],
	),
}

export const settingsDefinition = {
	eyebrow: 'Configure',
	title: 'Company Settings',
	icon: Settings,
	description: 'Control company identity, retention and common WhatsApp behavior.',
	primaryAction: 'Save settings',
	metrics: metrics(
		['Channels', '0', 'Assigned by Integration'],
		['Retention', '90 days', 'Message history'],
		['Time zone', 'Asia/Kolkata', 'Company default'],
	),
}
