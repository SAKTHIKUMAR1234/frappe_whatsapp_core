# Frappe WhatsApp Core

This app is a business-neutral plugin boundary, not another copy of the hub.

```text
Meta callback
   │ fast durable enqueue + immediate ACK
   ▼
NATS JetStream (file-backed middleman)
   │ 250 events or 2-minute window
   ▼
WhatsApp Core Event (one bulk DB insert + dedupe)
   │ one background batch job
   ├── Essdee adapter
   ├── Hospital adapter
   ├── Manufacturing adapter
   └── Future business adapter
```

Outbound commands use a separate JetStream work queue and are sent to Meta
one-by-one. Inbound logging is batched; WhatsApp delivery is never bulk-sent.
The Base owns only the event contract, durable processing state and handler
dispatch. A business app owns contacts, cases, permissions, workflows, ERP
links, AI tools and user interfaces.

## Visual flow engine

The flow engine is a Core feature. Business apps extend it with typed actions.

```text
Command / Template Button / Event / API
                    │
                    ▼
        Published Flow Trigger
                    │
                    ▼
 Question ──► Validate ──► Condition
                               ├──► Typed Action / Connector
                               └──► Human Handoff
                                          │
                                          ▼
                                         End
```

Each Frappe site stores its own flow definitions, immutable published versions,
running instances, context and step audit log. The relay never stores or
executes business flow state.

Publication is `Draft → Validate → Immutable Version`. Running conversations
remain pinned to the version on which they started. Every inbound event and
step run has an idempotency key, and a row lock serializes replies for one
conversation.

Canvas actions are allowlisted through `whatsapp_core_flow_actions`. They
cannot execute arbitrary Python, SQL or shell commands. An organization app
registers actions such as `case.create`, `customer.fetch`, or
`invoice.lookup`, while the Core engine remains business-neutral.

## Configurable business identity

```text
WhatsApp number
      │ normalize once
      ▼
Core Identity
      │ configured Identity Sources
      ▼
Identity Link(s) ──► any business DocType
      │
      ├── parent reference
      └── group reference
```

Core stores canonical identities and generic links. It does not know what a
retailer, patient or supplier is. A business app may register a typed resolver
for hierarchy rules; the resolver is selected by a fixed hook key, never an
arbitrary Python path stored in a database record.

Zero matches stay `Unresolved`, one match is `Resolved`, and multiple matches
are `Ambiguous` for review. Disabled sources deactivate their links on the
next resolution.
