function normalize(value) {
	return String(value || '')
		.normalize('NFKD')
		.replace(/[\u0300-\u036f]/g, '')
		.toLocaleLowerCase()
		.replace(/[^\p{L}\p{N}]+/gu, ' ')
		.trim()
}

function editDistance(left, right) {
	if (left === right) return 0
	if (!left.length) return right.length
	if (!right.length) return left.length
	let previous = Array.from({ length: right.length + 1 }, (_, index) => index)
	for (let leftIndex = 0; leftIndex < left.length; leftIndex += 1) {
		const current = [leftIndex + 1]
		for (let rightIndex = 0; rightIndex < right.length; rightIndex += 1) {
			current.push(
				Math.min(
					current[rightIndex] + 1,
					previous[rightIndex + 1] + 1,
					previous[rightIndex] + (left[leftIndex] === right[rightIndex] ? 0 : 1),
				),
			)
		}
		previous = current
	}
	return previous.at(-1)
}

function subsequenceScore(needle, haystack) {
	let cursor = 0
	let gaps = 0
	for (const character of needle) {
		const found = haystack.indexOf(character, cursor)
		if (found < 0) return -1
		gaps += found - cursor
		cursor = found + 1
	}
	return Math.max(25, 62 - gaps)
}

function tokenScore(token, text, words) {
	const position = text.indexOf(token)
	if (position >= 0) return 120 - Math.min(position, 40)
	let best = -1
	for (const word of words) {
		if (word.startsWith(token) || token.startsWith(word)) best = Math.max(best, 96)
		const allowance = token.length >= 7 ? 2 : token.length >= 4 ? 1 : 0
		if (allowance && Math.abs(word.length - token.length) <= allowance) {
			const distance = editDistance(token, word)
			if (distance <= allowance) best = Math.max(best, 82 - distance * 12)
		}
		best = Math.max(best, subsequenceScore(token, word))
	}
	return best
}

export function conversationSearchScore(row, query) {
	const normalizedQuery = normalize(query)
	if (!normalizedQuery) return 0
	const teamNames = (row.contact_teams || []).map((team) => team.team_name)
	if (row.assigned_team_details?.team_name) teamNames.push(row.assigned_team_details.team_name)
	const text = normalize(
		[row.display_name, row.phone_number, row.latest_message?.body, ...teamNames].join(' '),
	)
	const words = text.split(' ').filter(Boolean)
	const tokens = normalizedQuery.split(' ').filter(Boolean)
	let total = 0
	for (const token of tokens) {
		const score = tokenScore(token, text, words)
		if (score < 0) return -1
		total += score
	}
	return total
}

export function filterAndRankConversations(rows, query) {
	if (!normalize(query)) return rows
	return rows
		.map((row, index) => ({ row, index, score: conversationSearchScore(row, query) }))
		.filter((entry) => entry.score >= 0)
		.sort((left, right) => right.score - left.score || left.index - right.index)
		.map((entry) => entry.row)
}
