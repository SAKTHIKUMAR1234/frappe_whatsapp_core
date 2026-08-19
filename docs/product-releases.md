# WhatsApp product releases

Core and Hub are one product with independently deployable components. A
release is accepted only when the versions and machine contracts reported by
the applications agree; matching branch names or Git dates are not a
compatibility guarantee.

## Stable 1.0 contract

- WhatsApp Core: `1.0.x`
- WhatsApp Hub: `1.0.x`
- Go relay: `1.0.x`
- Core/Hub transport contract: `3`
- Hub/relay HTTP contract: `1`
- Supported Frappe majors: `15` and `16`

The authenticated Core transport identity includes a secret-free product
manifest. Hub validates it during onboarding, activation, and production
acceptance. Relay `/healthz` reports its product and contract version. Hub
**Setup & Readiness** shows the installed Hub, relay, and contract versions.

## Upgrade rule

Deploy Core to every connected site first, while the existing Hub and relay
continue running. Then deploy Hub, rebuild the relay through
`bench setup-whatsapp-processes`, restart the Hub process group, and run both
production acceptance gates. This order lets a new backward-compatible Core
advertise its contract before Hub begins enforcing it.

Never enable a route whose Setup & Readiness or production acceptance result
reports a missing or incompatible product manifest. Roll back all three
components to the recorded release commits when a compatibility gate fails;
do not bypass the check with an ad-hoc API or database edit.

The complete operational sequence remains in
[Deployment and operations](deployment-and-operations.md) and the Hub
`docs/production-platform-runbook.md`.
