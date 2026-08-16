import assert from 'node:assert/strict'
import test from 'node:test'

import {
	formatTemplateComponents,
	parseTemplateComponents,
	templateForm,
	templateRequest,
} from './templateAuthoring.js'

test('preserves a complete advanced Meta component document', () => {
	const components = [
		{ type: 'body', add_security_recommendation: true },
		{
			type: 'BUTTONS',
			buttons: [
				{
					type: 'OTP',
					otp_type: 'ZERO_TAP',
					package_name: 'com.example.app',
					signature_hash: 'signature',
				},
			],
		},
	]
	const request = templateRequest(
		{
			account_name: 'ACCOUNT-1',
			template_name: 'login_code',
			language_code: 'en_US',
			category: 'authentication',
			message_send_ttl_seconds: '600',
			components_json: JSON.stringify(components),
		},
		{ submit: true },
	)
	assert.equal(request.submit, true)
	assert.equal(request.template.message_send_ttl_seconds, 600)
	assert.equal(request.template.parameter_format, 'POSITIONAL')
	assert.equal(request.template.components[0].type, 'BODY')
	assert.deepEqual(request.template.components[1].buttons, components[1].buttons)
})

test('readback initializes the exact canonical component document', () => {
	const form = templateForm({
		account_name: 'ACCOUNT-1',
		template_name: 'order_update',
		components: [{ type: 'BODY', text: 'Order {{1}} is ready' }],
		message_send_ttl_seconds: 300,
	})
	assert.deepEqual(JSON.parse(form.components_json), [
		{ type: 'BODY', text: 'Order {{1}} is ready' },
	])
	assert.equal(form.message_send_ttl_seconds, 300)
})

test('fails closed instead of replacing malformed stored projection components', () => {
	assert.throws(() => templateForm({ components: '[{"type":"BODY"}' }), /valid JSON/)
})

test('fails closed on partial or malformed component documents', () => {
	assert.throws(() => parseTemplateComponents([{ type: 'HEADER', format: 'TEXT' }]), /BODY/)
	assert.throws(() => formatTemplateComponents('[{"type":"BODY"}'), /valid JSON/)
	assert.throws(
		() =>
			templateRequest({
				account_name: 'ACCOUNT-1',
				template_name: 'Bad Name',
				language_code: 'en',
				category: 'UTILITY',
				components_json: '[{"type":"BODY","text":"Hello"}]',
			}),
		/lowercase/,
	)
})
