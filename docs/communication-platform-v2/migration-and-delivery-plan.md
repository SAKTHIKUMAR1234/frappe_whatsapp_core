# Migration and delivery plan

## 1. Delivery principles

- No production credentials are used in development or automated tests.
- Existing WhatsApp traffic keeps one authoritative sender throughout the
  migration. Shadowing may compare normalized inputs/results but must not make a
  second provider send.
- Every phase has an observable acceptance gate, rollback point, and data
  reconciliation report.
- The existing Core and Hub contracts remain supported until all installed sites
  are migrated and the rollback window expires.
- Repository renames are deferred. First introduce generic contracts, then move
  packages when behavior is stable.

## 2. Work breakdown

### Phase 0 — decisions and contracts (1–2 weeks)

Deliver:

- architecture decision records for ownership, tenancy, PostgreSQL durability,
  object storage, signatures, event schemas, and adapter packaging;
- versioned event/command/capability schemas and compatibility rules;
- migration inventory for all current Core DocTypes, Hub records, JetStream
  streams/KV buckets, API routes, and operational settings;
- synthetic provider fixtures, performance budgets, and release test plan.

Gate: schemas can represent every current WhatsApp inbound/outbound/status,
template, group, call, media, retry, audit, and dead-letter fixture without
losing required meaning.

### Phase 1 — standalone Hub foundation (3–5 weeks)

Deliver:

- Go API, worker process, PostgreSQL migrations, connection pool, tenant
  middleware, KMS-backed secrets, object-storage client, and observability;
- event, command, transactional outbox/inbox, delivery lease, cursor,
  idempotency, operation, and dead-letter repositories;
- signed Core push and cursor pull-recovery APIs;
- Vue administration shell for tenants, connections, adapter state, deliveries,
  dead letters, and health;
- backup/restore and zero-downtime migration procedure.

Gate: synthetic adapters prove no event loss or duplicate materialization under
process crash, database failover, Core outage, webhook duplication, and worker
concurrency.

### Phase 2 — generic Communication Core (3–5 weeks)

Deliver:

- entity, person, endpoint, binding, thread, event, attachment, delivery, and
  case schemas plus migrations from compatible WhatsApp records;
- signed Hub ingress, idempotent batch materialization, cursor acknowledgement,
  local background jobs, and typed Socket.IO updates;
- business-app source registry and denormalized filter projections;
- channel-aware timeline/composer while preserving existing WhatsApp routes;
- compatibility facade for existing WhatsApp APIs and links.

Gate: existing local WhatsApp fixtures and UI workflows pass through both the
legacy facade and the generic model with equivalent permissions and results.

### Phase 3 — WhatsApp adapter parity and canary (2–3 weeks)

Deliver:

- port of existing Go relay behavior behind the adapter interface;
- Hub Frappe control-data exporter and standalone Hub importer;
- JetStream-to-PostgreSQL reconciliation/drain tool;
- read-only shadow normalizer comparison, followed by one-tenant canary;
- operational runbook, dashboards, alerts, rollback, and audit export.

Gate: provider fixture parity is complete, old/new normalized events compare,
all durable work is reconciled, and canary runs without unexplained divergence.

### Phase 4 — Telegram adapter (2–3 weeks)

Deliver bot connection setup, webhook security, update normalization,
send/reply/media/poll/edit/reaction support according to capabilities, rate
limits, Core endpoint binding, and UI channel identity.

Gate: sandbox bot E2E, duplicate/reorder/crash recovery, unavailable capability,
and group/topic permission tests pass.

### Phase 5 — email adapter (3–4 weeks)

Deliver SMTP/provider send, webhook or IMAP IDLE receive, cursor recovery,
RFC thread reconstruction, HTML sanitization, attachment scanning/storage,
bounce/complaint/suppression handling, and mailbox health UI.

Gate: provider sandbox plus local SMTP/IMAP fixtures pass threading, reconnect,
duplicate, malformed MIME, attachment, bounce, and security tests.

### Phase 6 — customer operations and UX completion (2–4 weeks, overlaps)

Deliver unified entity timeline, thread/channel switching, case grouping,
assignments, internal notes/mentions, personal folders, configured filters,
summary periods, search, accessibility, responsive design, and virtualized
high-volume lists.

Gate: representative user journeys pass at supported viewport sizes with no
full-list realtime reloads, focus traps, inaccessible controls, or unsupported
channel actions.

### Phase 7 — hardening and release (3–4 weeks)

Deliver load/soak/chaos/security tests, penetration findings, capacity model,
restore exercise, upgrade/rollback rehearsal, documentation, support playbooks,
SLO dashboards, and staged production rollout.

Gate: all release gates in `test-plan.md` pass and rollback is rehearsed from a
production-like backup.

## 3. Schedule and staffing

Some phases overlap, so calendar time differs from summed effort.

### Recommended team

- one Go/PostgreSQL engineer for Hub and adapters;
- one Frappe/Python engineer for Core, migrations, and business contracts;
- one frontend/QA engineer for Vue/Core UI, automation, accessibility, and E2E;
- part-time infrastructure/security review at architecture and release gates.

With this team, a responsible production release is **12–16 weeks**. One
engineer working sequentially should plan **24–32 weeks**. These ranges match
the detailed phase effort and include integration/release contingency. Provider
business verification, Meta/Telegram account approvals, email domain setup, and
production data anomalies can add external waiting time that code cannot solve.

## 4. Data migration

### Core

The migration writes new records alongside old records using deterministic keys:

- Channel -> Channel Connection projection;
- Identity/Alias/Link -> Endpoint/Person/Entity Binding;
- Conversation -> Thread;
- Message/Event -> Communication Event and Delivery;
- Internal Comment/Case/Team/Folder -> generalized equivalents.

It records source DocType/name, target key, checksum, status, and error. Batches
are resumable and commit independently. Invalid and ambiguous identities enter
a review report; they do not abort unrelated rows or silently merge customers.

During compatibility, old APIs read/write through the generic service layer.
There must not be two independent write implementations.

### Hub and JetStream

1. Export non-secret control metadata and wrap secrets for the new Hub KMS.
2. Import tenants, connections, routes, templates, limits, and Core
   subscriptions with validation but traffic disabled.
3. Shadow-normalize inbound webhook fixtures and compare results.
4. Pause new commands for a bounded maintenance window, let in-flight provider
   outcomes settle, and drain inbound/callback/audit streams.
5. Reconcile stream sequences, idempotency results, operation audit, dead
   letters, and Core cursors. Any unexplained item blocks cutover.
6. Enable one authoritative Hub route. Keep old stores immutable for rollback.

Queued outbound commands with an unknown provider outcome are never imported as
new sends. They require reconciliation or operator resolution.

## 5. Compatibility and rollout

Rollout stages:

1. local synthetic environment;
2. CI with provider emulators;
3. sandbox provider accounts;
4. internal non-critical Core site;
5. one low-volume production tenant canary;
6. gradual tenant cohorts;
7. default-new deployments;
8. legacy read-only period and retirement.

Feature flags exist at tenant/connection level for generic read model, new Hub
transport, adapter features, and new UI. They are operational controls, not
permanent alternate architectures.

## 6. Rollback

- Rollback never points two active senders at one connection.
- Before cutover, capture PostgreSQL backup, Core backup, Hub control export,
  immutable JetStream snapshot, cursor report, and deployed commit IDs.
- During the rollback window, the old Hub can be restored only after the new Hub
  is stopped and its accepted commands/events are exported and reconciled.
- Provider webhook ownership and DNS/API endpoints switch as one documented
  operation and are verified before traffic resumes.
- Core generic records remain; compatibility views can serve them. Destructive
  cleanup happens only after the retention and audit window.

## 7. Definition of done

The platform is done only when:

- WhatsApp, Telegram, and email meet their declared capability contracts;
- Core presents one entity timeline while preserving explicit reply routing;
- all event paths are durable, idempotent, replayable, and tenant isolated;
- migrations are resumable and reconciled with zero unexplained loss;
- production-like E2E, load, soak, chaos, security, backup, restore, upgrade,
  and rollback tests pass;
- operations can diagnose and resolve failures without database edits;
- user and operator documentation is complete and tested by someone who did not
  build the system.
