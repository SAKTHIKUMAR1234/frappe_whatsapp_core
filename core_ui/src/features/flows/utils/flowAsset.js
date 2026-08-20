function componentCount(value) {
	if (!value || typeof value !== 'object') return 0
	if (Array.isArray(value)) return value.reduce((total, item) => total + componentCount(item), 0)
	const own = value.type && value.type !== 'Form' ? 1 : 0
	return own + Object.values(value).reduce((total, item) => total + componentCount(item), 0)
}

export function describeFlowAsset(asset) {
	const screens = Array.isArray(asset?.screens) ? asset.screens : []
	return {
		version: String(asset?.version || '—'),
		screenCount: screens.length,
		componentCount: screens.reduce(
			(total, screen) => total + componentCount(screen?.layout?.children || []),
			0,
		),
		screens: screens.map((screen, index) => ({
			id: String(screen?.id || `screen-${index + 1}`),
			title: String(screen?.title || screen?.id || `Screen ${index + 1}`),
			terminal: Boolean(screen?.terminal),
		})),
	}
}
