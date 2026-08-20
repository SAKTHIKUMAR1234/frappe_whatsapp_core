export function routeComponentKey(route) {
	// Conversation changes are handled by InboxView's route watcher. Keeping one
	// stable instance preserves its realtime subscription, cached list and scroll.
	if (route?.name === 'inbox') return 'inbox'
	// The Flow workspace switches between Meta-hosted forms and Core automation
	// through a query parameter. FlowWorkspaceView reacts to that parameter in
	// place; remounting the same route inside an out-in transition can leave the
	// RouterView empty until a full browser refresh.
	if (route?.name === 'flows') return 'flows'
	return route?.fullPath || String(route?.name || '')
}
