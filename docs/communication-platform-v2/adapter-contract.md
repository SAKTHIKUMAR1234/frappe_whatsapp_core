# Channel adapter contract

An adapter translates one provider into the Hub's normalized command/event
model. It is not allowed to implement customer permissions, cases, folders, or
Core UI behavior.

## 1. Packaging and lifecycle

The first-party adapters compile into the Hub binary behind a versioned Go
interface. Later adapters may run as separately deployed services using the same
gRPC/HTTPS contract. Dynamic Go plugins are intentionally avoided because their
ABI and deployment coupling make safe upgrades difficult.

Every adapter registers:

- stable key and semantic version;
- supported connection kinds and credential schema;
- webhook routes and verification requirements;
- capability descriptor and provider limits;
- configuration validator and health probe;
- inbound normalizer, outbound executor, media handler, and reconciler;
- migrations for adapter-owned configuration only.

The adapter never owns shared Hub tables. Adapter-specific provider data is
stored as versioned JSON behind a normalized record or in explicitly registered
extension tables.

## 2. Capability descriptor

Capabilities are feature flags with constraints, not a single `enabled` value.
Examples:

- message types: text, rich text, image, video, audio, voice, document,
  location, contact, sticker, poll, template;
- message operations: reply, quote, react, edit, delete, forward;
- conversation rules: can initiate, opt-in required, template window, maximum
  text/media sizes, group support;
- receipts: accepted, sent, delivered, read, failed;
- calls: inbound, outbound, audio, video, recording, consent;
- management: templates, groups, bot commands, sender identities;
- bulk: supported, maximum batch, rate policy, approval/opt-out requirements.

Capabilities have `supported`, `configured`, `available`, `reason`, and optional
limits. Core renders an action only when all required states permit it. A
provider losing a capability results in a state event, not a broken control.

## 3. Required adapter operations

```text
Describe(ctx, connection) -> CapabilityDescriptor
ValidateConfig(ctx, draft) -> ValidationReport
VerifyWebhook(ctx, request) -> VerifiedEnvelope
NormalizeInbound(ctx, envelope) -> []NormalizedEvent
Execute(ctx, command) -> ProviderResult
FetchMedia(ctx, reference) -> MediaStream
Reconcile(ctx, cursor) -> ReconciliationPage
Health(ctx, connection) -> HealthReport
```

`Execute` must accept an immutable command and stable idempotency key. It returns
a classified outcome:

- `accepted`: provider accepted the command and supplied an external ID;
- `retryable`: transient/network/throttling failure with optional retry hint;
- `terminal`: invalid input, policy, consent, or permanent provider rejection;
- `unknown`: the request outcome cannot be proven; reconciliation is required
  before another provider call.

Unknown outcomes must never be blindly resent.

## 4. Normalized message schema

The common message payload contains text plus typed content blocks. Blocks are
versioned and include text, media reference, location, contact card, poll,
template invocation, quoted-event reference, and provider extension. Unknown
provider fields are retained in a protected raw envelope and represented as an
unsupported block rather than discarded.

Every event records its `channel_kind`, `connection_id`, `endpoint_id`,
`thread_id`, provider ID, provider timestamp, and normalized capability used.
This makes the source channel visible without leaking provider-specific JSON to
the user interface.

## 5. First-release adapter matrix

| Concern | WhatsApp | Telegram bot | Email |
| --- | --- | --- | --- |
| Receive | Meta signed webhooks | Bot API secret-path/header webhook | Provider webhook or IMAP IDLE worker |
| Send | Meta Graph API | Bot API | SMTP or provider API |
| Initiation | Consent/template rules | User must first start or expose a reachable chat | Any policy-allowed address |
| Thread key | Business account + phone/BSUID or group | Bot + chat + optional message thread | Mailbox + RFC message thread |
| Rich types | Provider-supported messages, templates, calls, groups | Text/media/location/contact/poll, edits/reactions where allowed | Sanitized HTML/text and attachments |
| Receipts | Sent/delivered/read/failed where supplied | Provider acknowledgements and available updates | Accepted/bounce/complaint; read is generally unavailable |
| Bulk | Template/policy/rate constrained | Bot opt-in and strict rate constrained | Consent, unsubscribe, reputation, bounce constrained |
| Media | Download promptly, store immutable object reference | Download by file ID promptly | Decode, scan, and store attachments |

## 6. WhatsApp adapter

The existing Go relay behavior is the reference implementation. The migration
must preserve:

- signature verification before durable acceptance;
- WABA/phone route resolution and strict tenant scoping;
- per-conversation ordering with cross-conversation concurrency;
- stable idempotency around Meta sends;
- status, template, call, group, flow, and media event normalization;
- provider error classification and pair-rate throttling;
- final result delivery even when Core was unavailable during the send.

Credential and template management moves from Hub Frappe to the Hub management
API and Vue UI. Core retains template projections needed by local users.

## 7. Telegram adapter

The first version targets bots:

- configure token through the encrypted connection flow;
- register a webhook with a secret verification value;
- map `update_id` to ingress idempotency and `chat_id` to an endpoint;
- preserve reply/quote, edit, reaction, callback query, media, poll, topic, and
  group context only when the bot and API expose them;
- store Telegram file references immediately and fetch media within provider
  lifetime;
- enforce Bot API rate limits per bot and chat;
- reject attempts to initiate an arbitrary user who has not started/reached the
  bot, returning an actionable capability reason;
- reconcile webhook offsets/health without accepting both polling and webhook
  ingestion simultaneously.

Telegram Business capabilities, if adopted later, are a distinct connection
mode and capability set, not assumptions added to the bot adapter.

## 8. Email adapter

Email requires more than SMTP:

- outbound can use SMTP or a provider API;
- inbound uses provider webhooks where available, otherwise one supervised IMAP
  IDLE connection per mailbox with cursor/UID recovery;
- threads use `Message-ID`, `In-Reply-To`, and `References`, with a conservative
  subject fallback only when identifiers are absent;
- HTML is sanitized and remote content is blocked/proxied by policy;
- attachments are size-checked, content-sniffed, malware-scanned, and stored in
  object storage;
- bounces, complaints, suppressions, unsubscribe, and mailbox failures become
  typed events;
- SPF, DKIM, DMARC, domain verification, and sender reputation are operational
  readiness checks;
- email open/read tracking is never presented as a guaranteed read receipt.

## 9. External business connector

ERP, sales, and help-desk systems publish business events through a separate
connector contract. A connector can create a typed timeline event or request a
Core business action; it cannot impersonate a user message or bypass entity
permissions.

Required inputs are tenant, source system, source event ID, entity binding,
event type, occurred time, payload schema version, and idempotency key. Examples
include delivery challan created, GRN received, invoice overdue, and ticket
resolved.

## 10. Adapter certification gates

An adapter is releasable only when it passes:

- contract fixtures for every declared capability;
- duplicate webhook and duplicate command tests;
- malformed signature/payload and tenant-isolation tests;
- disconnect, timeout, throttling, provider 5xx, and unknown-outcome tests;
- media size/type/expiry and SSRF tests;
- schema forward/backward compatibility tests;
- provider sandbox or approved test-account end-to-end tests;
- a capability audit proving the UI exposes no unsupported operation.
