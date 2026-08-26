export function frappeLoginUrl(routePath = '/') {
	const base = window.location.pathname || '/whatsapp'
	const target = `${base}#${String(routePath || '/').startsWith('/') ? routePath : `/${routePath}`}`
	return `/login?redirect-to=${encodeURIComponent(target)}`
}

export function redirectToFrappeLogin(routePath = '/', { replace = true } = {}) {
	const url = frappeLoginUrl(routePath)
	if (replace) window.location.replace(url)
	else window.location.assign(url)
}
