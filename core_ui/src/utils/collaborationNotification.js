export function collaborationNotificationRoute(notification, focusToken = '') {
	const conversation = String(notification?.conversation || '').trim()
	const comment = String(notification?.document_name || notification?.comment?.name || '').trim()
	const references = Array.isArray(notification?.comment?.message_references)
		? notification.comment.message_references
		: []
	const message = String(references.find((value) => String(value || '').trim()) || '').trim()
	const query = {}
	if (comment) query.comment = comment
	if (message) query.message = message
	if (focusToken) query.focus = String(focusToken)
	return {
		name: 'inbox',
		params: conversation ? { conversation } : {},
		query,
	}
}
