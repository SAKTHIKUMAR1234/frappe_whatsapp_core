export async function acceptIncomingMedia({
	invoke,
	rtc,
	accountName,
	callId,
	answer,
	timeout = 20000,
	onPhase = () => {},
	onClaimed = () => {},
}) {
	if (!answer?.sdp || answer.sdp_type !== 'answer') {
		throw new Error('The secure audio answer could not be prepared.')
	}
	onPhase('pre_accepting')
	await invoke({
		account_name: accountName,
		action: 'pre_accept',
		call_id: callId,
		sdp_type: answer.sdp_type,
		sdp: answer.sdp,
	})
	onClaimed()
	onPhase('connecting')
	if (!(await rtc.waitUntilConnected(timeout))) {
		throw new Error(
			'The secure audio path could not connect. Check this network’s UDP or TURN access and try again.',
		)
	}
	onPhase('accepting')
	return invoke({
		account_name: accountName,
		action: 'accept',
		call_id: callId,
	})
}
