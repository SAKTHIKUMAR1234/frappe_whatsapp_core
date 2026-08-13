const dateTimeFormatter = new Intl.DateTimeFormat('en-IN', {
	day: 'numeric',
	month: 'short',
	year: 'numeric',
	hour: 'numeric',
	minute: '2-digit',
	hour12: true,
})

const timeFormatter = new Intl.DateTimeFormat('en-IN', {
	hour: 'numeric',
	minute: '2-digit',
	hour12: true,
})

const shortDateFormatter = new Intl.DateTimeFormat('en-IN', {
	day: 'numeric',
	month: 'short',
})

const yearDateFormatter = new Intl.DateTimeFormat('en-IN', {
	day: '2-digit',
	month: '2-digit',
	year: '2-digit',
})

export function parseDateTime(value) {
	if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
	if (!value) return null
	let normalized = String(value).trim()
	if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(normalized))
		normalized = normalized.replace(' ', 'T')
	// JavaScript supports milliseconds, while MariaDB/Frappe emits microseconds.
	normalized = normalized.replace(/(\.\d{3})\d+/, '$1')
	const parsed = new Date(normalized)
	return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function formatDateTime(value, fallback = '—') {
	const parsed = parseDateTime(value)
	return parsed ? dateTimeFormatter.format(parsed) : fallback
}

export function formatTime(value, fallback = '') {
	const parsed = parseDateTime(value)
	return parsed ? timeFormatter.format(parsed) : fallback
}

export function formatConversationTime(value, now = new Date()) {
	const parsed = parseDateTime(value)
	const reference = parseDateTime(now)
	if (!parsed || !reference) return ''
	const day = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate())
	const today = new Date(reference.getFullYear(), reference.getMonth(), reference.getDate())
	const daysAgo = Math.round((today.getTime() - day.getTime()) / 86_400_000)
	if (daysAgo === 0) return timeFormatter.format(parsed)
	if (daysAgo === 1) return 'Yesterday'
	if (parsed.getFullYear() === reference.getFullYear()) return shortDateFormatter.format(parsed)
	return yearDateFormatter.format(parsed)
}
