export function foldersMatch(left, right) {
	if (!left || !right) return false
	if (left.name && right.name && left.name === right.name) return true
	return left.folder_type === 'Important' && right.folder_type === 'Important'
}
