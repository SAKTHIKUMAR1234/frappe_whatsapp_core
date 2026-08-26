# WhatsApp Core and Hub v2 productization review

This document is the implementation contract for the next productization pass.
It consolidates the current Core and Hub behavior, the required customer-operations
experience, the known gaps, and the evidence required before release.

## Product outcome

WhatsApp Core is a daily customer-operations workspace built on WhatsApp, not a
thin chat client. A signed-in operator must be able to understand ownership,
priority, unread work, recent context, internal collaboration, and the next action
without reading an entire conversation or learning implementation terminology.

WhatsApp Hub owns Meta credentials and management operations. The Go relay owns
the high-volume Meta data plane and durable JetStream queues. Core owns local
customer history, business links, team access, operator preferences, and the UI.
No UI route may expose transport credentials or require an operator to understand
NATS, relay topology, raw JSON, database identifiers, or internal record names.

## Non-negotiable boundaries

- Development and verification use local sites and synthetic credentials only.
- Production is not read, written, restarted, or used as test infrastructure.
- Existing user changes in either repository are preserved.
- No commit or push is part of this review unless separately requested.
- Core remains compatible with Frappe 15 and 16.
- Hub and relay remain compatible with the documented 3 GiB managed store cap.
- A phone number is the outbound destination. Internal identity records must never
  redirect a send to another phone number.
- Team and folder filters narrow access or presentation; they never widen access.

## Current baseline

The current code already implements these foundations:

| Capability | Current implementation |
| --- | --- |
| Team queues | Permission-scoped team summaries, members, contacts, assignment, avatars |
| Personal folders | Built-in Important folder and up to 30 private custom folders |
| Inbox navigation | Folder/team routes with unread badges and deep-linkable query state |
| Search | Server and client ranking across names, phones, aliases, and team names |
| Large inboxes | Cursor pagination, a virtualized conversation list, deferred unread hydration |
| Conversation history | Bidirectional pages, scroll restoration, targeted message deltas |
| Collaboration | Internal comments, read coverage, and expiring conversation presence |
| Customer context | Chat and structured Summary views with business links and risks |
| Attachments | Local media cache plus image/document preview components |
| Meta operations | Templates, Flows, groups, campaigns, calling, and WebRTC controls |
| Transport | Hub-managed Meta routing and a Go/JetStream relay with bounded storage |
| Operations | Tenant-scoped operation history and operator-controlled dead letters |

These capabilities must be refined and integrated. They must not be replaced by
parallel UI-only state or a second identity/access model.

## Confirmed gaps

### Dead-letter lifecycle

Ordinary work items already have bounded transport retries. Terminal inbound,
status, callback, and audit failures enter `WA_DEAD`; operators can inspect,
redrive, resolve, or delete them. The existing 72-hour stream `MaxAge` and cleanup
remove records by age, but there is no controlled automatic dead-letter redrive
lifecycle.

Required behavior:

1. A new dead letter is retained with its original failure and immutable sequence.
2. Eligible non-outbound entries are redriven automatically after a bounded delay.
3. A redrive is idempotently reserved before publishing the work item.
4. A failed cycle records the outcome and schedules the next cycle without a hot loop.
5. At most three automatic redrive cycles are permitted.
6. An unresolved entry is automatically deleted only when it is at least 72 hours
   old and has exhausted all three automatic redrive cycles.
7. A relay outage cannot let JetStream age out an entry before those conditions are
   satisfied; application cleanup owns that policy.
8. Outbound entries remain manual because replaying a send with an uncertain Meta
   outcome can duplicate a customer-visible message.
9. Manual redrive, resolution, and deletion remain idempotent and auditable.

### Customer-operations workspace

- Folder and team overview states need a compact workload summary, not explanatory
  paragraphs or empty decorative cards.
- Folder membership needs a discoverable action on a conversation and an immediate,
  user-targeted realtime update.
- Presence must show only other active operators, deduplicated by user across tabs.
  It must not create persistent business records.
- Reader avatars remain compact. Full "read by" and "not read by" details belong in
  a stable popover/dialog that can be reached by keyboard and does not disappear while
  the pointer moves into it.
- Random Frappe record names and Meta IDs are never primary user-facing labels.
- Team selectors render the display name while submitting the immutable document key.
- The inbox remains mounted while route tabs change; navigation must not require a
  browser refresh or trigger a full list/message reload.
- Realtime message, status, call, folder, team, presence, and comment events update only
  affected rows/components. Reconnect performs bounded reconciliation.

### Sessions, clustering, categories, and summaries

A conversation remains the authoritative chronological audit. A customer-facing
"session" is a presentation projection over a contiguous range of messages:

- Session boundaries are deterministic and stored as message references, never copies.
- The first implementation uses an inactivity boundary and explicit operator split or
  merge actions; AI may suggest boundaries later but cannot silently rewrite history.
- Each session shows time range, participants, categories, open actions, risks, and a
  short summary.
- Opening a session can reveal the underlying messages in the normal chat stream.
- Categories attach to messages/conversations through the existing category model.
- Summaries cite their coverage range and generation time, expose refresh state, and
  fail without hiding the source conversation.
- Internal comments are visually distinct, team-only, audited, and never sent to Meta.

### Media and calls

- Inbound media is cached while the signed Meta URL is valid. UI reads the Core-owned
  private file thereafter and shows a stable skeleton with final dimensions reserved.
- Image and document previews open in an accessible dialog; downloads keep their real
  filename and type.
- A call is scoped by the same team rules as its contact. Once one operator claims a
  call, other operators see who answered without ending that call. A second call remains
  independently claimable.
- The call timeline belongs to the same customer conversation and exposes the combined
  local/remote recording artifact where recording consent and infrastructure permit it.
- Calling or Groups navigation is hidden or clearly unavailable when the account lacks
  the capability; configuration objects are not printed to users.

### Templates and flows

- Hub is the Meta credential boundary; Core is the operator-facing template catalog.
- A Hub sync converges the complete applicable catalog to each connected Core site.
- A Core edit synchronizes through Hub and returns an actionable state, not raw JSON.
- Template authoring includes positional/named sample values and does not force a
  template when the 24-hour customer-service window is open.
- The 24-hour window updates from inbound realtime events without reloading the page.
- Flow graphs render deterministic non-overlapping layouts. Actions are configured in
  the node inspector and runtime permission failures are handled by the owning business
  action rather than leaked as generic Frappe tracebacks.

## Interaction and visual standard

- Use a restrained product surface: one primary action per region, concise labels,
  consistent spacing, predictable hierarchy, and no ornamental status cards.
- Every action has hover, focus-visible, pressed, disabled, loading, empty, error, and
  success states where applicable.
- Keyboard navigation and screen-reader names are first-class behavior.
- Touch targets are at least 44 by 44 CSS pixels on touch layouts.
- Motion uses transform/opacity, has no layout jumps, and honors
  `prefers-reduced-motion`.
- Media dimensions and skeletons reserve layout space before content arrives.
- The phone layout uses one pane at a time; tablet/desktop layouts preserve list context.
- Typography, contrast, truncation, and responsive density are validated at 320, 375,
  768, 1024, 1440, and 1920 CSS-pixel widths.

The Vercel `web-design-guidelines` skill is the external, framework-neutral audit
checklist for accessibility, navigation state, responsive interaction, motion, images,
and rendering performance. React-specific guidance does not apply to this Vue codebase.

## Performance contract

- Conversation list payloads are cursor-bounded and never include the full read ledger.
- Unread badges hydrate only for the visible virtual window and are batched.
- Message history loads bounded pages around the last-read anchor or newest edge.
- Realtime events mutate normalized local rows rather than refetching entire resources.
- Search is debounced, cancellable, permission-scoped, and has bounded server results.
- Presence uses expiring Redis state and emits only when the viewer set changes.
- Expensive dashboard and summary requests run only while their route is mounted.
- No unbounded polling, DOM list, database query, JetStream reservation, or log payload is
  accepted in the release gate.

## Acceptance test matrix

| Area | Automated evidence | Browser evidence |
| --- | --- | --- |
| Dead letters | Three scheduled cycles, backoff, restart recovery, idempotency, 72-hour gate, outbound exclusion | Monitor exposes attempts, next retry, terminal state, and safe actions |
| Permissions | Manager, team member, unassigned user, unrelated team, guest, machine identity | Hidden/disabled navigation and 403-safe UI states |
| Inbox lifecycle | Route remount, stale request cancellation, reconnect, targeted deltas | Switch every route without refresh or list reset |
| Large inbox | Cursor stability, visible unread batching, search ranking | Virtual scroll with synthetic high-volume rows |
| Read state | Last-read anchor, partial visibility, compact coverage | Scroll interruption, reload, jump latest, stable details popover |
| Folders | Create, rename, reorder, add/remove, ownership isolation | Telegram-style navigation and immediate badge/membership updates |
| Teams/presence | Scope, multiple tabs, expiry, claim conflicts | Two operators viewing and calling the same/different contacts |
| Sessions/summary | Boundary determinism, source coverage, merge/split, failure fallback | Summary-to-source navigation and readable empty/loading/error states |
| Media | Signed URL expiry, local cache, permission, filename/type | Image/document/audio layouts without content shift |
| Templates/flows | Full convergence, samples, idempotency, action permissions | Structured editors and non-overlapping flow graph |
| Calling/groups | Capability gates, SDP/state transitions, independent claim | Responsive call controls, ringtone, audio path, timeline |
| Accessibility | Component unit checks and static audit | Keyboard-only pass, focus order, reduced motion, contrast |
| Compatibility | Python and Frappe version guards, Go tests, production build | Local Frappe 15 and 16 smoke paths using synthetic data |

## Release gate

The release is not ready because a feature exists or a build succeeds. It is ready only
when the matching Core, Hub, and relay contracts pass their unit, integration, browser,
responsive, permission, failure-recovery, and resource checks with recorded evidence.
Known failures remain visible in this document or the test output; they are not hidden by
fallback UI, broad exception handling, direct database edits, or manual production repair.
