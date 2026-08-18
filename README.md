### Frappe WhatsApp Core

Reusable, configurable WhatsApp business workflow foundation

Supports Frappe **15 and 16** and Python 3.10 or newer.

For the complete Hub → relay/JetStream → Core deployment order, trust
boundaries, machine credentials, legacy migration, readiness recovery, and
release acceptance gates, read
[Deployment and operations](docs/deployment-and-operations.md). It is the
canonical Core-side setup guide; do not copy settings into Supervisor or Nginx
by hand.

For the shortest role-based installation and daily-use path, start with
[Getting started](docs/getting-started.md).

Open `/whatsapp` for the Core application. The legacy `/whatsapp_core` entry
remains supported, and each entry keeps its own browser-history base so inbox
deep links and back navigation do not jump between aliases.

### MCP and AI agents

The authenticated Streamable HTTP endpoint at
`/api/method/frappe_whatsapp_core.mcp_transport.handle` exposes audited tools
for inbox search and infinite history, rich replies, read/typing state,
bookmarks, teams, party binding, campaigns, native Meta Flows, Groups and
Calling. Destructive Flow, group and campaign actions require explicit
confirmation values, and every invocation is recorded in
`WhatsApp Core MCP Invocation`.

### Native WhatsApp Flows

Open `/whatsapp`, then use **Meta Flows** to create, upload, preview, publish,
clone, migrate, deprecate and inspect Meta-hosted WhatsApp Flows. Core records
native Flow replies in the conversation log and does not render its own copy of
the customer Flow. Flow migration and encrypted data-endpoint provisioning are
performed through the configured Integration Hub. Integration owns Meta
signatures and encryption keys; Core receives only authenticated decrypted
payloads and dispatches them to registered
`whatsapp_core_meta_flow_endpoint_handlers`. Every exchange is idempotently
recorded in `WhatsApp Core Meta Flow Exchange`.

### Groups and Calling

Where Meta enables the corresponding Business Platform products for the
account, Core manages Meta-hosted WhatsApp Groups, including lifecycle, invite links,
approved invite templates, join approvals, participants, text/media/template
messages, pinned messages and per-participant receipts. It also supports
WhatsApp Business Calling settings, permission requests, call buttons and
templates, deep links, WebRTC signaling, voicemail announcements, opt-in
recording/transcription artifacts and durable call-event logs. Meta's calling
control plane is handled here; audio media runs through the configured WebRTC
or SIP infrastructure.

### Realtime delivery contract

Integration separates webhook traffic before it reaches Core. Inbound customer
messages, message echoes, calls and group activity use an immediate JetStream
lane. Core materializes them in the same authenticated request and emits one
Socket.IO event after the database transaction commits. Parallel relay workers
may handle different conversations while a conversation lock preserves message
order within one chat.

Delivery/read receipts and management status events use a separate batching
lane (100 by default, up to 1,000 per relay window). Core stores those events in
one request, processes them in bounded chunks and sends compact UI deltas after
commit. Socket.IO reconnect triggers reconciliation, so a temporary connection
loss cannot become a permanently missing message.

### Business contact resolution

Core owns the canonical WhatsApp identity and can link it to documents that
already belong to the installed Frappe site. A WhatsApp Manager configures each
allowed DocType under **Core Settings → Contact sources**, including its phone,
display-name and optional entity-type fields. Parent fields and one-level child
table phone fields are supported.

Outbound delivery resolves the current number in this order:

1. a source-specific `whatsapp_core_contact_phone_resolvers` hook;
2. a document `get_whatsapp_contact_number(context=...)` or
   `get_contact_number(context=...)` method;
3. the configured contact-source phone field.

An app can register a source-specific resolver without changing Core:

```python
whatsapp_core_contact_phone_resolvers = {
    "sales_partner": "my_app.whatsapp.resolve_partner_number",
}
```

The resolver receives `identity`, `link`, `source`, `document` and `context`
and returns either a phone string or `{ "phone_number": "..." }`. Core rejects
missing records, empty configured numbers and ambiguous resolver registrations
with an actionable validation error instead of silently sending to stale data.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app frappe_whatsapp_core
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/frappe_whatsapp_core
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
