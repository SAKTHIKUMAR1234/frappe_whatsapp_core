export function routeComponentKey(route) {
	// Conversation changes are handled by InboxView's route watcher. Keeping one
	// stable instance preserves its realtime subscription, cached list and scroll.
	if (route?.name === 'inbox') return 'inbox'
	return route?.fullPath || String(route?.name || '')
}
