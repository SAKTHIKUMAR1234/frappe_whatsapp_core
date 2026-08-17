# WhatsApp Core deployment and operations

This guide is the canonical Core-side procedure for a production deployment.
The Hub repository's `docs/production-platform-runbook.md` is the canonical
host and relay procedure. Follow both in order; do not create a second set of
NATS, Meta, or machine-user settings in a customer app.

## Architecture and fixed routing

There are three components and two HTTP planes:

1. **Integration Hub (Frappe v16)** owns Meta WABAs, phone numbers, permanent
   access tokens, app secrets, templates, native Flows, groups/calling
   configuration, connected sites, and the relay route snapshot.
2. **Go relay + NATS JetStream** is the live data plane. Meta webhook
   verification/delivery, message send/batch, read/typing, live call signaling,
   and media transfer go directly through the relay. The relay durably delivers
   inbound events and outbound results to Core.
3. **WhatsApp Core (Frappe v15/v16)** owns conversations, messages, operator
   state, teams, campaigns, automation, cases, party binding, and the Fusion UI.
   Customer business apps use Core's public hooks/APIs; they do not retain old
   WhatsApp DocTypes, roles, tokens, or send logic.

Template/Flow definition lifecycle and group/calling configuration use Hub
Frappe because they are management operations. Live message, media, webhook,
and calling traffic uses Go so peak traffic does not traverse Hub web workers.
No Nginx route customization is required by the apps.

All Meta Graph endpoints are version `v26.0`. A test may override the graph
origin only to a loopback URL. Never store production credentials in source,
fixtures, browser tests, logs, screenshots, or shell history.

## Installation order

1. Back up every Hub and Core site, record app commits, and take the normal
   infrastructure snapshot.
2. Deploy and migrate `frappe_whatsapp_hub` on the Hub bench twice.
3. In **Hub Relay Settings**, elect exactly one runtime provider, configure the
   single managed NATS and relay listener, then choose **NATS File Store (GiB)**
   `1`, `2`, or `3`. This field is authoritative for the NATS file-store cap and
   the proportional stream/KV reservations. Keep at least 2 GiB additional
   host space free. Do not edit `run-nats-from-bench.sh`, Supervisor, or a NATS
   file to tune storage.
4. Run `bench setup-whatsapp-processes --site <hub-site>`, register the
   generated process definitions with the selected process manager, and start
   NATS before the relay.
5. Configure the Hub platform and Meta account. The public Meta callback is
   `<public-relay-origin>/webhooks/meta`; it is not a Frappe API URL.
6. Deploy and migrate `frappe_whatsapp_core` on each customer site twice, then
   build its assets.
7. Install or update the customer's business app. It must remain usable when
   Core is absent and activate its WhatsApp adapter only when Core is installed.
8. Migrate legacy data using `docs/legacy-whatsapp-migration.md`. The migration
   copies into Core and preserves old tables read-only; it does not require
   dropping customer data during cutover.

Core bench commands:

```bash
cd <frappe-bench>
bench --site <core-site> backup --with-files
bench --site <core-site> migrate
bench --site <core-site> migrate
bench build --app frappe_whatsapp_core
bench --site <core-site> clear-cache
```

## One unified Core machine identity

On Core, provision one service-only Website User with capability `all`:

```bash
bench --site <core-site> execute \
  frappe_whatsapp_core.frontend_api.provision_transport_credentials \
  --kwargs '{"user_email":"wa-core-<site>@internal.example","capability":"all"}'
```

The command returns the API secret once. Transfer the key and secret through a
secret manager into the Hub Connected Site's encrypted **Core API Key** and
**Core API Secret** fields. Never assign these roles to a human or Desk user,
and never add operator roles to the machine user. The unified identity owns
only the ingress, template-projection, and Flow-exchange machine roles.

The Hub provisions a separate route-scoped credential for Core to call the
relay. Save that one-time pair in **WhatsApp Core Settings** with:

- the exact public Hub origin;
- the exact relay service origin, with no path, query, or fragment;
- the channel-to-Hub-account mapping;
- WhatsApp and outbound enabled only after preflight succeeds.

`Go Relay URL must contain only a service origin` means the value must resemble
`https://relay.example.com`, not a `/webhooks/meta`, `/v1/outbound`, or Frappe
method URL. Core appends the fixed route itself.

## Readiness and fault recovery

- `/healthz` proves that the Go process is alive.
- `/readyz` proves that at least one complete enabled route has loaded. A
  `503 no_routes` response is safe standby, not a reason to proxy around the
  relay. Inspect Connected Site diagnostics and complete the missing account,
  WABA, phone number, URLs, or unified Core credential.
- A `401` or `403` Core callback is a configuration failure. The relay defers
  that item without exhausting ordinary delivery retries. Reprovision the
  unified capability-`all` Core identity, update the encrypted Connected Site
  pair, refresh the route, and retry the operation.
- A transient Core/Meta `5xx`, timeout, or rate limit uses bounded retry with
  backoff. Terminal invalid requests enter the dead-letter stream with the
  operation and error evidence. Investigate and use the Relay Monitor's
  guarded operator retry; do not purge JetStream to hide an error.
- NATS API error counters are cumulative since process start. The monitor shows
  the current value and request total; an old non-increasing value is not an
  active incident. Alert on new deltas, backlog, redelivery, DLQ growth, storage
  pressure, or readiness loss.
- Socket.IO events contain no tenant row data. They tell authenticated clients
  to reconcile through permission-filtered APIs. Reconnect therefore cannot
  permanently lose a message, status, reaction, reader, or unread update.

## Operator and data semantics

- Unread and last-read state are per user. Opening a conversation starts at the
  current user's last-read position (or first unread on first use).
- Visibility dwell marks only messages actually viewed. Refresh resumes at the
  last viewed message; unread holes above or below remain unread.
- **Jump to new messages** asks the backend for the latest page before moving
  the viewport; it does not pretend the currently loaded page is complete.
- Reader labels use the Frappe user's display name. Email addresses are not
  exposed as the primary tooltip label.
- Core primary names are short random identifiers. Stable provider/business
  identifiers live in unique indexed fields. The migration rewrites Link,
  Dynamic Link, JSON, child, and Singles references transactionally and audits
  dangling legacy names before completion.

## Release acceptance gate

Do not enable customer traffic until all of the following pass on non-production
recipients and synthetic data:

1. Hub `/healthz` and `/readyz`; exactly one enabled route; no unexplained DLQ.
2. Meta callback verification plus signed inbound text/media/reaction/status.
3. Outbound text, approved template, media, reply context, read, and typing.
4. Sent → delivered → read projection, duplicate and out-of-order callbacks,
   retryable and terminal failures, malformed provider success, and operator
   retry.
5. The 100-message per-user unread/resume/jump browser journey and Socket.IO
   reconnect reconciliation.
6. Group and Calling management through Hub plus live group/call traffic through
   the relay. Calling icon visibility must be omitted when unset and otherwise
   be `DEFAULT` or `DISABLE_ALL`.
7. AI categorization, visual automation, typed inputs, attachments, `/exit`,
   and permission-isolated machine replies.
8. A browser-driven 18,000-recipient campaign with bounded rate/retry,
   idempotent recipients, no stale queued rows, no duplicate provider IDs, and
   no database deadlocks.
9. Two consecutive site migrations, the short-name audit, the full Core/Hub
   suites, business-app adapter suites, and a clean production diff review.

Production inspection is read-only during diagnosis. Apply a release only from
reviewed commits, with backups and rollback commits recorded; never repair a
production credential or business record through ad-hoc SQL.
