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

## Templates and campaigns

Template ownership stays in the Integration application. Core receives only a
site-local, read-only projection after the Hub assigns a template.

```text
Integration Desk
 create / edit / Meta approval / site assignment
                    │ authenticated push
                    ▼
          Core Template Catalog
                    │ select
                    ▼
Exact business audience ──► Prepared campaign
                                   │
                 Meta approved ────┤
                 named SEND gate ──┤
                                   ▼
                        Business sender adapter
                                   │
                      one recipient at a time
                                   ▼
                         Durable relay queue
```

Audience resolution is a business-app responsibility. Core stores only exact
Core identity references and a JSON source description. Preparing an audience
does not queue anything. Meta approval and human SEND authorization are
separate gates; editing the campaign definition revokes SEND authorization.

## External AI boundary

```text
AI client ── authenticated MCP JSON-RPC ──► Core tools
                                              ├── list unclassified messages
                                              ├── upsert topic summary
                                              ├── list conversation topics
                                              └── create typed case
```

Core does not embed an AI model. The stateless endpoint is
`/api/method/frappe_whatsapp_core.mcp_transport.handle`; Frappe API
authentication, Core roles, origin validation, site isolation and an immutable
invocation audit apply before a tool executes.
