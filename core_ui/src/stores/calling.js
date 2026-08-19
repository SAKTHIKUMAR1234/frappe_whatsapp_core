import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'
import { call, errorMessage } from '@/services/frappe'
import { subscribe } from '@/services/realtime'
import { acceptIncomingMedia } from '@/features/calling/services/callSignaling'
import {
	TERMINAL_CALL_STATES,
	WhatsAppWebRTCSession,
	nextIncomingCall,
	normalizedCallStatus,
	parseCallSession,
} from '@/features/calling/services/whatsappWebRTC'

function providerCallId(result) {
	const value = result?.data || result || {}
	return String(value?.calls?.[0]?.id || value?.call_id || '').trim()
}

function contactName(value) {
	return (
		value?.display_name ||
		value?.presentation?.display_name ||
		value?.label ||
		value?.remote_username ||
		value?.remote_number ||
		'WhatsApp contact'
	)
}

export const useCallingStore = defineStore('core-calling', () => {
	const workspace = ref({
		accounts: [],
		calls: [],
		contacts: [],
		calls_has_more: false,
		calls_next_start: 0,
		calls_page_size: 30,
		calling: { enabled: false, status: 'UNAVAILABLE' },
	})
	const loading = ref(false)
	const loadingMore = ref(false)
	const initialized = ref(false)
	const error = ref('')
	const notice = ref('')
	const selectedAccount = ref('')
	const active = ref(null)
	const muted = ref(false)
	const remoteStream = shallowRef(null)
	const elapsedSeconds = ref(0)
	let rtc = null
	let unsubscribe = () => {}
	let currentUser = ''
	let siteName = ''
	let durationTimer = null

	const accounts = computed(() => workspace.value.accounts || [])
	const contacts = computed(() => workspace.value.contacts || [])
	const calls = computed(() => workspace.value.calls || [])
	const callingEnabled = computed(() => Boolean(workspace.value.calling?.enabled))
	const canManage = computed(() => Boolean(workspace.value.can_manage))
	const incoming = computed(() =>
		nextIncomingCall(calls.value, active.value?.call_id),
	)
	const busy = computed(() => Boolean(active.value))

	function accountForChannel(channel) {
		return (
			accounts.value.find((item) => item.channel === channel)?.account_name ||
			selectedAccount.value
		)
	}

	function upsertCall(item) {
		if (!item?.call_id && !item?.name) return
		const index = calls.value.findIndex(
			(row) =>
				(item.name && row.name === item.name) ||
				(item.call_id && row.call_id === item.call_id),
		)
		const merged = index >= 0 ? { ...calls.value[index], ...item } : item
		if (index >= 0) calls.value.splice(index, 1, merged)
		else {
			calls.value.unshift(merged)
			if (workspace.value.calls_has_more) {
				workspace.value.calls_next_start =
					Number(workspace.value.calls_next_start || 0) + 1
			}
		}
	}

	async function applyRealtime(event) {
		const item = event?.call
		if (!item) return
		const wasIncoming = incoming.value?.call_id === item.call_id
		upsertCall(item)
		if (wasIncoming && item.handled_by && item.handled_by !== currentUser)
			notice.value = `${contactName(item)}'s call is being handled by another team member.`
		if (active.value?.call_id !== item.call_id) return
		active.value = { ...active.value, ...item }
		const remote = parseCallSession(item.session)
		if (remote?.type === 'answer') {
			try {
				await rtc?.applyRemoteAnswer(remote)
			} catch (exception) {
				error.value = errorMessage(exception, 'The call answer could not be applied.')
			}
		}
		if (TERMINAL_CALL_STATES.has(normalizedCallStatus(item.status))) {
			finishCall(item.status === 'rejected' ? 'Call declined.' : 'Call ended.')
		}
	}

	async function load(accountName = selectedAccount.value, { quiet = false } = {}) {
		if (!quiet) loading.value = true
		error.value = ''
		try {
			const result = await call('frappe_whatsapp_core.calling.calling_workspace', {
				account_name: accountName || null,
			})
			workspace.value = result || workspace.value
			selectedAccount.value = result?.selected_account || ''
			error.value = result?.error || ''
			return result
		} catch (exception) {
			error.value = errorMessage(exception, 'Calling is temporarily unavailable.')
			throw exception
		} finally {
			if (!quiet) loading.value = false
		}
	}

	async function initialize(site, user) {
		if (initialized.value && siteName === site && currentUser === user) return
		destroy()
		siteName = site || ''
		currentUser = user || ''
		unsubscribe = subscribe(siteName, 'whatsapp_core_call', applyRealtime)
		try {
			await load('')
		} catch {
			// The page presents the actionable availability error.
		}
		initialized.value = true
	}

	async function selectAccount(value) {
		if (!value || value === selectedAccount.value) return
		await load(value)
	}

	async function loadMoreCalls() {
		if (loadingMore.value || !workspace.value.calls_has_more) return
		loadingMore.value = true
		error.value = ''
		try {
			const result = await call('frappe_whatsapp_core.calling.call_history', {
				start: workspace.value.calls_next_start || calls.value.length,
				limit: workspace.value.calls_page_size || 30,
			})
			const known = new Set(
				calls.value.map((row) => row.name || row.call_id).filter(Boolean),
			)
			for (const row of result?.rows || []) {
				const key = row.name || row.call_id
				if (key && !known.has(key)) {
					calls.value.push(row)
					known.add(key)
				}
			}
			workspace.value.calls_has_more = Boolean(result?.has_more)
			workspace.value.calls_next_start = Number(result?.next_start || calls.value.length)
			workspace.value.calls_page_size = Number(
				result?.page_size || workspace.value.calls_page_size || 30,
			)
			return result
		} catch (exception) {
			error.value = errorMessage(exception, 'More call history could not be loaded.')
			throw exception
		} finally {
			loadingMore.value = false
		}
	}

	async function enableCalling() {
		error.value = ''
		await call('frappe_whatsapp_core.calling.enable_calling', {
			account_name: selectedAccount.value,
		})
		workspace.value.calling = { enabled: true, status: 'ENABLED' }
		notice.value = 'WhatsApp calling is enabled.'
	}

	function createRtc() {
		rtc?.close()
		remoteStream.value = null
		rtc = new WhatsAppWebRTCSession(workspace.value.rtc_configuration || {}, {
			onRemoteStream: (stream) => {
				remoteStream.value = stream
			},
			onConnectionState: (state) => {
				if (!active.value) return
				if (state === 'connected') {
					active.value = { ...active.value, phase: 'connected' }
					startDuration()
				}
				if (['failed', 'closed'].includes(state) && active.value.phase !== 'ending') {
					error.value = state === 'failed' ? 'The call audio connection failed.' : ''
				}
			},
		})
		return rtc
	}

	async function startCall(contact) {
		if (busy.value) throw new Error('Finish the current call before starting another.')
		if (!contact?.identity) throw new Error('Select a contact to call.')
		if (!callingEnabled.value) throw new Error('WhatsApp calling is not enabled.')
		error.value = ''
		notice.value = ''
		active.value = {
			call_id: '',
			remote_identity: contact.identity,
			display_name: contactName(contact),
			remote_number: contact.phone_number || contact.secondary_text || '',
			direction: 'Outbound',
			phase: 'preparing',
			account_name: selectedAccount.value,
		}
		try {
			const session = await createRtc().prepareOutgoing()
			active.value.phase = 'calling'
			const result = await call('frappe_whatsapp_core.calling.call_action', {
				account_name: selectedAccount.value,
				action: 'connect',
				identity: contact.identity,
				sdp_type: session.sdp_type,
				sdp: session.sdp,
			})
			const callId = providerCallId(result)
			if (!callId) throw new Error('Meta did not return a call identifier.')
			active.value = { ...active.value, call_id: callId, status: 'connect' }
			return result
		} catch (exception) {
			finishCall()
			error.value = errorMessage(exception, 'The WhatsApp call could not be started.')
			throw exception
		}
	}

	async function answerCall(item = incoming.value) {
		if (!item?.call_id) return
		if (busy.value) throw new Error('Finish the current call before answering another.')
		error.value = ''
		active.value = {
			...item,
			display_name: contactName(item),
			phase: 'answering',
			account_name: accountForChannel(item.channel),
		}
		let locallyClaimed = false
		let providerClaimed = false
		try {
			await call('frappe_whatsapp_core.calling.claim_incoming_call', {
				account_name: active.value.account_name,
				call_id: item.call_id,
			})
			locallyClaimed = true
			const answer = await createRtc().prepareIncoming(item.session)
			await acceptIncomingMedia({
				invoke: (args) => call('frappe_whatsapp_core.calling.call_action', args),
				rtc,
				accountName: active.value.account_name,
				callId: item.call_id,
				answer,
				onClaimed: () => {
					providerClaimed = true
				},
				onPhase: (phase) => {
					if (active.value?.call_id === item.call_id)
						active.value = { ...active.value, phase }
				},
			})
			active.value = { ...active.value, phase: 'connected', handled_by: currentUser }
		} catch (exception) {
			if (providerClaimed) {
				try {
					await call('frappe_whatsapp_core.calling.call_action', {
						account_name:
							active.value?.account_name || accountForChannel(item.channel),
						action: 'terminate',
						call_id: item.call_id,
					})
				} catch {
					// Meta may already have closed a failed negotiation.
				}
			} else if (locallyClaimed) {
				try {
					await call('frappe_whatsapp_core.calling.release_incoming_call_claim', {
						account_name:
							active.value?.account_name || accountForChannel(item.channel),
						call_id: item.call_id,
					})
				} catch {
					// A concurrent provider event may have made the claim non-releasable.
				}
			}
			finishCall()
			error.value = errorMessage(exception, 'The incoming call could not be answered.')
			throw exception
		}
	}

	async function declineCall(item = incoming.value) {
		if (!item?.call_id) return
		error.value = ''
		try {
			await call('frappe_whatsapp_core.calling.call_action', {
				account_name: accountForChannel(item.channel),
				action: 'reject',
				call_id: item.call_id,
			})
			upsertCall({ ...item, status: 'rejected' })
		} catch (exception) {
			error.value = errorMessage(exception, 'The incoming call could not be declined.')
			throw exception
		}
	}

	async function hangUp() {
		const current = active.value
		if (!current) return
		active.value = { ...current, phase: 'ending' }
		try {
			if (current.call_id) {
				await call('frappe_whatsapp_core.calling.call_action', {
					account_name: current.account_name || accountForChannel(current.channel),
					action: 'terminate',
					call_id: current.call_id,
				})
			}
		} catch (exception) {
			error.value = errorMessage(exception, 'Meta did not confirm the hang-up.')
		} finally {
			finishCall('Call ended.')
		}
	}

	function toggleMute() {
		muted.value = rtc?.setMuted(!muted.value) || false
	}

	function startDuration() {
		if (durationTimer) return
		durationTimer = window.setInterval(() => {
			elapsedSeconds.value += 1
		}, 1000)
	}

	function finishCall(message = '') {
		window.clearInterval(durationTimer)
		durationTimer = null
		elapsedSeconds.value = 0
		muted.value = false
		rtc?.close()
		rtc = null
		remoteStream.value = null
		active.value = null
		if (message) notice.value = message
	}

	function clearMessages() {
		error.value = ''
		notice.value = ''
	}

	function destroy() {
		unsubscribe()
		unsubscribe = () => {}
		finishCall()
		initialized.value = false
		siteName = ''
		currentUser = ''
	}

	return {
		workspace,
		loading,
		loadingMore,
		initialized,
		error,
		notice,
		selectedAccount,
		active,
		muted,
		remoteStream,
		elapsedSeconds,
		accounts,
		contacts,
		calls,
		callingEnabled,
		canManage,
		incoming,
		busy,
		initialize,
		load,
		selectAccount,
		loadMoreCalls,
		enableCalling,
		startCall,
		answerCall,
		declineCall,
		hangUp,
		toggleMute,
		clearMessages,
		destroy,
	}
})
