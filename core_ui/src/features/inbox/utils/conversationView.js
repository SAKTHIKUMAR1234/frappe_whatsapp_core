export function defaultConversationView(detail, savedMode = '') {
	if (savedMode === 'chat' || savedMode === 'summary') return savedMode
	return detail?.contact_summary?.summary || detail?.topics?.length ? 'summary' : 'chat'
}

export function conversationViewStorageKey(conversation) {
	return `whatsapp:conversation-view:${String(conversation || '')}`
}
