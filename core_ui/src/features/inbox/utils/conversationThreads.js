function timestamp(value) {
	const time = new Date(value || 0).getTime()
	return Number.isFinite(time) ? time : 0
}

export function presentConversationThreads(topics = []) {
	return (topics || [])
		.filter((topic) => topic?.name && topic?.title)
		.map((topic) => ({
			name: topic.name,
			title: String(topic.title).trim(),
			summary: String(topic.summary || '').trim(),
			category: String(topic.category || '').trim(),
			status: String(topic.status || 'Open').trim(),
			source: String(topic.source || '').trim(),
			messageCount: Math.max(0, Number(topic.message_count || 0)),
			firstMessage: topic.first_message || topic.messages?.[0] || '',
			lastMessage: topic.last_message || topic.messages?.[topic.messages.length - 1] || '',
			startedAt: topic.first_message_at || '',
			endedAt: topic.last_message_at || topic.first_message_at || '',
		}))
		.sort(
			(left, right) =>
				timestamp(right.endedAt) - timestamp(left.endedAt) ||
				left.title.localeCompare(right.title),
		)
}

export function threadStatusTone(status) {
	const normalized = String(status || '').toLowerCase()
	if (normalized === 'resolved') return 'success'
	if (normalized === 'waiting') return 'warn'
	if (normalized === 'archived') return 'secondary'
	return 'info'
}
