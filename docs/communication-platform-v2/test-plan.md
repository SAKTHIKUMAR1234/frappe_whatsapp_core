# Test plan

All automated tests use synthetic tenants and provider emulators. Sandbox
accounts are used only for the final provider E2E layer. Production credentials,
tokens, messages, media, and customer data are forbidden in test fixtures and
logs.

## 1. Test layers

1. **Schema and unit tests** — event/command compatibility, normalizers,
   classifiers, repositories, permission predicates, UI components.
2. **Contract tests** — every adapter and Core version runs against the same
   versioned fixtures and invalid-input corpus.
3. **Integration tests** — Go, PostgreSQL, object storage, provider emulator,
   Frappe Core, Redis/Socket.IO, and browser run together.
4. **Provider sandbox tests** — actual WhatsApp, Telegram bot, and selected email
   providers using non-production identities.
5. **E2E browser tests** — permissions, timeline, composer, cases, folders,
   filters, notes, media, realtime, reconnect, responsive UI, accessibility.
6. **Load/soak/chaos tests** — sustained traffic, bursts, hot tenants,
   disconnects, restarts, failover, recovery, and retention.
7. **Migration tests** — anonymized-shaped datasets, invalid records, resume,
   reconciliation, cutover, and rollback.

## 2. Core domain matrix

| Area | Required cases |
| --- | --- |
| Entity resolution | one endpoint/one entity; multiple endpoints/one person; multiple people/one company; unknown endpoint; manual merge; incorrect merge reversal; ambiguous match; tenant collision |
| Bindings | multiple local DocTypes; disabled source; deleted/renamed source; permission-limited source; deterministic resync; conflicting primary binding |
| Threads | separate channel ordering; unified entity timeline ordering; explicit reply route; archived/resolved/reopened; concurrent inbound/outbound |
| Cases | create from one/many events; cross-channel case; assign/reassign; mention; resolve/reopen; unauthorized team; deleted source event projection |
| Internal collaboration | note not sent to provider; message selection; assignment notification; reply/resolve; team-only visibility; manager visibility; no cross-team Socket.IO leak |
| Flows and automation | trigger match; collect input; branch; wait/resume; registered business action; permission-safe service context; duplicate event; invalid action; timeout; human handoff; version change while active; audit and recovery |
| Teams/folders | unassigned scope; member scope; manager all-scope; personal folder CRUD/order; unread totals; contact move; disabled member; concurrent edits |
| Filters | Checkbox, Link, Select, MultiSelect, Date, number, fuzzy text; nulls; stale projection; business record update; disallowed field/operator; pagination and stable sort |
| Search | name, normalized endpoint, aliases, message text according to policy, accents, case, minor typo, partial number; tenant/team isolation; bounded query plan |
| Summary | period boundaries; late-arriving event; media transcript absent; permission changes; regeneration; source citations; no automatic action from untrusted text |

## 3. Adapter matrix

### Shared contract

- duplicate and concurrently duplicated webhook;
- reordered provider events and late status;
- duplicate outbound command with same and mismatched payload hash;
- transient, terminal, throttled, authentication, and unknown outcomes;
- provider timeout before and after acceptance;
- adapter restart during normalization and provider execution;
- capability changes while a composer is open;
- expired, oversized, misleading-type, and malicious media;
- schema field added by provider and unknown message type;
- tenant/connection identifier spoofing;
- reconciliation after an event gap.

### WhatsApp

- webhook challenge and signature rejection/acceptance;
- text and every supported media/contact/location/template/interactive type;
- sent, delivered, read, failed, deleted, and out-of-order statuses;
- 24-hour window transition in realtime and template fallback;
- phone/BSUID aliases without cross-recipient sends;
- pair-rate throttle, provider 4xx/5xx, and unknown send outcome;
- template sync/update/delete and sample parameters;
- call/group/flow events only when capability is configured;
- inbound media cached before provider URL expiry;
- template create/sync/update/delete, positional/named sample values, language,
  status projection, and Core/Hub reconciliation;
- call permission, inbound ringing fan-out, one-agent answer ownership, a second
  concurrent call, SDP offer/answer, ICE/STUN/TURN, timeout/terminate, remote and
  local audio recording, consent, artifact retention, and team-scoped realtime;
- group capability discovery, membership/permission changes, messages, statuses,
  unsupported state, and refresh/reconciliation;
- Meta Flow exchange, encryption, response action, registered Core business
  action, duplicate callback, permission context, failure, and resume;
- durable Hub acceptance replaces the queued UI state; accepted/sent,
  delivered, read, failed, and late corrective statuses render correctly;
- existing Core/Hub fixture parity.

### Telegram

- secret webhook validation and duplicate `update_id`;
- private chat, group, channel, and topic isolation where bot permissions allow;
- user-never-started-bot initiation rejection;
- text, media group, voice, contact, location, poll, callback, reply, edit,
  reaction, and deleted/unsupported update;
- `file_id` reuse/download, expiry/retry, and large-file limits;
- per-bot/per-chat rate limiting and `retry_after` handling;
- bot removed, blocked, permissions reduced, webhook replaced, and recovery;
- polling and webhook modes cannot ingest simultaneously.

### Email

- plain text, HTML, multipart/alternative, nested MIME, inline image, attachments;
- `Message-ID`/`In-Reply-To`/`References` threading and missing/broken headers;
- IMAP reconnect/UID cursor, duplicate fetch, mailbox resync, provider webhook
  duplicate/reorder;
- outbound SMTP/API accepted, temporary reject, permanent reject, timeout, and
  unknown outcome;
- bounce, complaint, suppression, unsubscribe, auto-reply, and mail loop;
- HTML/script/remote-image sanitization, filename traversal, zip bomb, malware,
  oversized attachment, and content-type mismatch;
- DKIM/domain/readiness status and credential rotation;
- no false guaranteed-read state.

## 4. Durable delivery and failure matrix

For each crash point below, assert that the event is either not committed or is
eventually visible exactly once in Core's materialized model:

1. before provider webhook transaction;
2. after event insert but before outbox insert attempt;
3. after transaction commit but before `NOTIFY`;
4. after claim but before HTTP delivery;
5. after Core commit but before acknowledgement reaches Hub;
6. after acknowledgement but before Hub cursor update;
7. during lease expiry with two workers;
8. during PostgreSQL primary failover;
9. while Core is offline beyond ordinary retry age;
10. during dead-letter automatic redrive;
11. during schema-version rolling deployment;
12. during object upload after event acceptance.

Specific assertions:

- polling recovers work even when all notifications are dropped;
- leases, retry count, next attempt, and error classification survive restart;
- the highest contiguous cursor in each subscription partition never skips an
  uncommitted sequence;
- a worker commits its lease before network I/O and lease expiry cannot create
  concurrent ownership outside the idempotent delivery contract;
- one poison item is isolated without permanently blocking unrelated threads or
  subscription partitions, and its cursor gap stays visible;
- per-thread order holds while unrelated threads execute concurrently;
- terminal dead letters are retained for policy duration and pruned only after
  retry cycles/audit conditions are met;
- manual resolve/redrive is tenant scoped, authorized, audited, and idempotent;
- a redrive cannot repeat a provider send with an unknown/final outcome.

## 5. Security tests

- forged/expired/replayed Hub and provider signatures;
- credential substitution and cross-tenant connection ID;
- Hub OIDC login/logout/session expiry, MFA policy, CSRF, role escalation,
  tenant switching, revoked membership, and audited privilege changes;
- horizontal and vertical privilege escalation in all Core APIs;
- Socket.IO room subscription for another team/entity/tenant;
- SQL injection through filters, JSON, search, cursor, adapter extensions;
- SSRF, redirect-to-private-network, DNS rebinding, and oversized media fetch;
- stored/reflected XSS in text, email HTML, names, filenames, provider errors;
- malicious MIME, archive bombs, decompression bombs, and path traversal;
- secret/PII leakage in logs, traces, metrics, exports, errors, and Vue state;
- KMS outage, credential rotation/revocation, stale worker credential handle;
- rate-limit bypass, webhook flooding, idempotency-key exhaustion, hot tenant;
- backup/restore encryption and deletion/retention enforcement;
- dependency and container scanning plus least-privilege deployment review.

## 6. UI and accessibility tests

- login uses Frappe authentication and redirects to the requested Core route;
- navigation mounts the destination without refresh and restores browser history;
- opening a thread loads a bounded anchor window; realtime adds/patches only the
  affected rows and does not reload the complete inbox;
- composer autofocus, reply focus, keyboard send/newline behavior, and focus
  restoration after dialogs;
- channel and endpoint are unambiguous before send;
- unsupported actions are hidden/disabled with one actionable reason;
- media skeleton reserves final dimensions; preview supports image, audio,
  video, and document without layout shift;
- virtualized inbox supports keyboard navigation and screen readers;
- folder/team/filter controls retain readable labels and correct Link values;
- notes, mentions, cases, summaries, read details, and channel labels work with
  keyboard and touch;
- empty/loading/error/offline/reconnecting/permission-revoked states;
- 320, 375, 768, 1024, 1440, and 1920 px widths plus zoom to 200%;
- WCAG 2.2 AA automated checks and manual keyboard/screen-reader review;
- reduced motion, high contrast, dark/light themes, and no tooltip-only action.

## 7. Load and performance tests

Workloads include:

- steady ingress/outbound at projected 1x, 3x, and 10x tenant load;
- webhook burst and status storm;
- one hot conversation plus many cold conversations;
- one noisy tenant alongside normal tenants;
- 5,000-recipient approved command with provider rate limiting;
- one million events, large read/folder/team tables, and deep cursor pagination;
- Core outage followed by backlog drain without overwhelming Frappe workers;
- PostgreSQL restart/failover and object-storage latency;
- 24-hour soak with retries, media, rotations, and deploys.

Initial release targets, to be confirmed by the capacity benchmark, are:

- zero lost committed events and zero duplicate Core materializations;
- Hub webhook acceptance p95 under 250 ms excluding provider network;
- command durable acceptance p95 under 300 ms;
- normal Hub-to-Core event visibility p95 under 2 seconds;
- inbox initial useful render p75 under 1.5 seconds on the supported reference
  dataset and network;
- no tenant can consume more than its configured worker/database/storage budget;
- backlog drains predictably without violating provider or Core rate limits.

Every result records dataset, hardware, concurrency, percentiles, database query
plans, CPU, memory, disk, connection count, and queue age. Average latency alone
is not an acceptance result.

## 8. Migration and compatibility tests

- clean site, current production-shaped site, partially migrated site, and
  legacy invalid records;
- deterministic rerun and interruption after every batch boundary;
- duplicate phone/BSUID, shared number, malformed phone, multiple bindings,
  missing channel, orphan message, and ambiguous customer;
- checksums and count reconciliation per source/target type;
- existing URL/API/role compatibility while the facade is enabled;
- old/new normalization shadow comparison without double sending;
- JetStream pending, acknowledging, callbacks, audit, operations, KV results,
  and dead letters reconciled before cutover;
- forward upgrade, rollback, provider webhook switch, and second forward upgrade;
- backup restore to an isolated environment followed by reconciliation.

## 9. Release gates

Release is blocked unless:

- unit/contract/integration/E2E suites are green and non-flaky;
- each channel passes sandbox certification for declared capabilities;
- migration reconciliation has zero unexplained records;
- load, soak, and chaos targets pass on production-like sizing;
- security review has no open critical/high finding;
- backup, restore, upgrade, rollback, and credential rotation are rehearsed;
- dashboards alert on queue age, retry age, dead letters, provider failures,
  Core delivery failures, cursor gaps, database saturation, and storage growth;
- operations and customer documentation has been executed end-to-end by a
  reviewer who did not implement the feature;
- canary has a documented observation period and rollback owner.
