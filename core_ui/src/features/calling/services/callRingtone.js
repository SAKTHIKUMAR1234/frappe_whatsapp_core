let audioContext = null
let cadenceTimer = null
const activeOscillators = new Set()

function context() {
	const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext
	if (!AudioContext) return null
	audioContext ||= new AudioContext()
	return audioContext
}

export async function unlockRingtone() {
	const value = context()
	if (!value) return false
	if (value.state === 'suspended') {
		try {
			await value.resume()
		} catch {
			return false
		}
	}
	return value.state === 'running'
}

function ringPulse() {
	const value = context()
	if (!value || value.state !== 'running') return
	const startedAt = value.currentTime
	const gain = value.createGain()
	gain.gain.setValueAtTime(0.0001, startedAt)
	gain.gain.exponentialRampToValueAtTime(0.12, startedAt + 0.03)
	gain.gain.setValueAtTime(0.12, startedAt + 0.82)
	gain.gain.exponentialRampToValueAtTime(0.0001, startedAt + 0.9)
	gain.connect(value.destination)
	for (const frequency of [440, 480]) {
		const oscillator = value.createOscillator()
		oscillator.type = 'sine'
		oscillator.frequency.setValueAtTime(frequency, startedAt)
		oscillator.connect(gain)
		activeOscillators.add(oscillator)
		oscillator.addEventListener('ended', () => activeOscillators.delete(oscillator), {
			once: true,
		})
		oscillator.start(startedAt)
		oscillator.stop(startedAt + 0.92)
	}
}

export async function startRingtone() {
	stopRingtone()
	if (!(await unlockRingtone())) return false
	ringPulse()
	cadenceTimer = globalThis.setInterval(ringPulse, 2800)
	return true
}

export function stopRingtone() {
	globalThis.clearInterval(cadenceTimer)
	cadenceTimer = null
	for (const oscillator of activeOscillators) {
		try {
			oscillator.stop()
		} catch {
			// The oscillator may already have reached the scheduled stop time.
		}
	}
	activeOscillators.clear()
}
