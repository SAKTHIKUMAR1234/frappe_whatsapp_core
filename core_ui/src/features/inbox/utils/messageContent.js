function object(value) {
	return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function array(value) {
	return Array.isArray(value) ? value : []
}

function text(value) {
	return value === null || value === undefined ? '' : String(value).trim()
}

export function parseMessageContent(value) {
	if (value && typeof value === 'object') return value
	try {
		return JSON.parse(value || '{}')
	} catch {
		return {}
	}
}

export function normalizeMessageContent(message = {}) {
	const envelope = parseMessageContent(message.content)
	const type = text(message.message_type || envelope.type || 'unknown').toLowerCase()
	const payload = envelope.payload ?? envelope[type] ?? {}
	const fallback = text(message.body)

	if (type === 'button') {
		const button = object(payload)
		return {
			kind: 'choice',
			label: 'Button reply',
			title: text(button.text || button.payload || fallback) || 'Button selected',
			meta: text(button.payload) !== text(button.text) ? text(button.payload) : '',
		}
	}

	if (type === 'interactive') {
		const interactive = object(payload)
		const reply = object(
			interactive.button_reply || interactive.list_reply || interactive.product_reply,
		)
		if (Object.keys(reply).length) {
			return {
				kind: 'choice',
				label: interactive.list_reply ? 'List reply' : 'Interactive reply',
				title: text(reply.title || reply.description || fallback) || 'Option selected',
				meta: text(reply.description || reply.id),
			}
		}
	}

	if (type === 'location') {
		const location = object(payload)
		const latitude = Number(location.latitude)
		const longitude = Number(location.longitude)
		const hasCoordinates = Number.isFinite(latitude) && Number.isFinite(longitude)
		return {
			kind: 'location',
			label: 'Location',
			title: text(location.name || fallback) || 'Shared location',
			body: text(location.address),
			url:
				text(location.url) ||
				(hasCoordinates
					? `https://www.google.com/maps?q=${encodeURIComponent(`${latitude},${longitude}`)}`
					: ''),
			coordinates: hasCoordinates ? `${latitude}, ${longitude}` : '',
		}
	}

	if (type === 'contacts') {
		const contacts = array(payload).length ? array(payload) : array(object(payload).contacts)
		return {
			kind: 'contacts',
			label: contacts.length === 1 ? 'Contact' : `${contacts.length} contacts`,
			contacts: contacts.map((row) => {
				const contact = object(row)
				const name = object(contact.name)
				const organization = object(contact.org)
				return {
					name:
						text(name.formatted_name) ||
						[text(name.first_name), text(name.last_name)].filter(Boolean).join(' ') ||
						'Contact',
					phones: array(contact.phones)
						.map((phone) => text(phone?.phone || phone?.wa_id))
						.filter(Boolean),
					emails: array(contact.emails)
						.map((email) => text(email?.email))
						.filter(Boolean),
					organization: text(organization.company || organization.title),
				}
			}),
		}
	}

	if (type === 'order') {
		const order = object(payload)
		const items = array(order.product_items).map((item) => ({
			id: text(item?.product_retailer_id),
			quantity: Number(item?.quantity || 0),
			price: text(item?.item_price),
			currency: text(item?.currency),
		}))
		return {
			kind: 'order',
			label: 'Order',
			title: `${items.length} ${items.length === 1 ? 'item' : 'items'}`,
			meta: text(order.catalog_id),
			items,
		}
	}

	if (type === 'referral') {
		const referral = object(payload)
		return {
			kind: 'referral',
			label: 'Referral',
			title: text(referral.headline || fallback) || 'Ad referral',
			body: text(referral.body),
			url: text(referral.source_url),
			mediaUrl: text(referral.image_url || referral.video_url || referral.thumbnail_url),
		}
	}

	if (type === 'system') {
		const system = object(payload)
		return {
			kind: 'system',
			label: 'WhatsApp update',
			title: text(system.body || fallback) || 'Account information changed',
			meta: text(system.type).replaceAll('_', ' '),
		}
	}

	if (type === 'poll' || type === 'poll_creation' || type === 'poll_response') {
		const poll = object(payload)
		const options = array(poll.options || poll.selected_options).map((option) =>
			text(option?.title || option?.name || option?.option || option),
		)
		return {
			kind: 'poll',
			label: type === 'poll_response' ? 'Poll response' : 'Poll',
			title: text(poll.question || poll.name || fallback) || 'Poll',
			options: options.filter(Boolean),
		}
	}

	if (type === 'unsupported' || type === 'unknown') {
		return {
			kind: 'unsupported',
			label: 'Unsupported message',
			title: fallback || 'This message type is not available in the inbox.',
		}
	}

	return {
		kind: 'text',
		label: type.replaceAll('_', ' '),
		title: fallback || 'Message',
	}
}
