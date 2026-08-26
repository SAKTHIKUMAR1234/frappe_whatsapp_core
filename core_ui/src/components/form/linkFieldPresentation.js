export function linkOptionValue(option, optionValue) {
	return option?.[optionValue]
}

export function findLinkOption(rows, value, optionValue) {
	return (rows || []).find((option) => linkOptionValue(option, optionValue) === value) || null
}

export function linkOptionLabel(option, optionLabel, optionValue) {
	return option?.[optionLabel] || linkOptionValue(option, optionValue) || ''
}
