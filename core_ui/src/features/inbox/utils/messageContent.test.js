import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeMessageContent } from './messageContent.js'

test('presents shared contacts with useful names and channels', () => {
	const value = normalizeMessageContent({
		message_type: 'contacts',
		content: JSON.stringify({
			type: 'contacts',
			contacts: [
				{
					name: { formatted_name: 'Maya Rao' },
					phones: [{ phone: '+91 90000 00000' }],
					emails: [{ email: 'maya@example.com' }],
					org: { company: 'Andrometiq' },
				},
			],
		}),
	})

	assert.equal(value.kind, 'contacts')
	assert.deepEqual(value.contacts[0], {
		name: 'Maya Rao',
		phones: ['+91 90000 00000'],
		emails: ['maya@example.com'],
		organization: 'Andrometiq',
	})
})

test('creates a safe map link only when coordinates are valid', () => {
	const value = normalizeMessageContent({
		message_type: 'location',
		content: { location: { latitude: 11.01, longitude: 76.96, name: 'Office' } },
	})

	assert.equal(value.title, 'Office')
	assert.match(value.url, /^https:\/\/www\.google\.com\/maps\?q=/)
	assert.equal(normalizeMessageContent({ message_type: 'location', content: '{}' }).url, '')
})

test('renders order and interactive reply envelopes without exposing JSON', () => {
	const order = normalizeMessageContent({
		message_type: 'order',
		content: {
			order: {
				catalog_id: 'catalog-1',
				product_items: [
					{
						product_retailer_id: 'SKU-1',
						quantity: 2,
						item_price: '50',
						currency: 'INR',
					},
				],
			},
		},
	})
	const reply = normalizeMessageContent({
		message_type: 'interactive',
		content: {
			interactive: { list_reply: { id: 'red', title: 'Red', description: 'Colour' } },
		},
	})

	assert.equal(order.items[0].id, 'SKU-1')
	assert.equal(reply.title, 'Red')
	assert.equal(reply.meta, 'Colour')
})
