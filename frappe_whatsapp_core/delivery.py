"""Monotonic provider delivery-state transitions."""

DELIVERY_RANK = {
	"Queued": 0,
	"Sent": 1,
	"Delivered": 2,
	"Read": 3,
}


def advance_delivery_status(current: str | None, incoming: str) -> str:
	"""Return a state that never regresses after a late provider callback."""
	current = current or "Queued"
	if incoming == "Deleted" or current == "Deleted":
		return "Deleted"
	if incoming == "Failed":
		return current if current in {"Delivered", "Read"} else "Failed"
	if current == "Failed":
		return current
	if incoming not in DELIVERY_RANK:
		return current
	if current not in DELIVERY_RANK:
		return incoming
	return (
		incoming
		if DELIVERY_RANK[incoming] > DELIVERY_RANK[current]
		else current
	)
