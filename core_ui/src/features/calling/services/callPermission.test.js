import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeCallPermission } from './callPermission.js'

test('normalizes string, boolean, and nested permission responses', () => {
	assert.deepEqual(normalizeCallPermission({ permission: 'GRANTED' }), {
		status: 'granted',
		label: 'Allowed',
		allowed: true,
		expiresAt: '',
	})
	assert.equal(normalizeCallPermission({ data: [{ can_call: true }] }).allowed, true)
	assert.equal(
		normalizeCallPermission({ permission: { status: 'DENIED' } }).label,
		'Not allowed',
	)
})

test('never exposes an object as the permission label', () => {
	const permission = normalizeCallPermission({
		data: { call_permission_status: { status: 'PENDING', expiration_time: '2030-01-01' } },
	})
	assert.equal(permission.label, 'Pending approval')
	assert.equal(permission.expiresAt, '2030-01-01')
	assert.notEqual(permission.label, '[object Object]')
})
