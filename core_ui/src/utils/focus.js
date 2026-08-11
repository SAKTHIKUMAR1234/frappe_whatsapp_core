export function focusDialogControl(dialogRef, selector = 'input, textarea, [role="combobox"]') {
	window.requestAnimationFrame(() => {
		const component = dialogRef?.value || dialogRef
		const componentRoot = component?.$el || component
		const visibleDialogs = [...document.querySelectorAll('[role="dialog"]')].filter(
			(dialog) => dialog.getClientRects().length,
		)
		const root =
			componentRoot?.querySelector?.(selector) && componentRoot
				? componentRoot
				: visibleDialogs.at(-1)
		root?.querySelector?.(selector)?.focus({ preventScroll: true })
	})
}
