# Frappe WhatsApp Core

This app is the complete business-neutral WhatsApp product installed on every
company site. It is not another copy of the Hub.

```text
Meta callback
   │ fast durable enqueue + immediate ACK
   ▼
NATS JetStream (file-backed middleman)
   │ 250 events or 250-millisecond window
   ▼
WhatsApp Core Event (one bulk DB insert + dedupe)
   │ one background batch job
   ├── Essdee adapter
   ├── Hospital adapter
   ├── Manufacturing adapter
   └── Future business adapter
```

Outbound commands use a separate JetStream work queue and are sent to Meta
one-by-one. A second durable callback queue returns the provider message ID and
final send result to Core before later delivery/read webhooks arrive. Inbound
logging is micro-batched; WhatsApp delivery is never bulk-sent. Core owns
identity, party binding, shared inbox, optimistic outbound, conversation,
message, case, campaign, flow, AI queue and MCP contracts. A company app is
optional. When installed, it adds business hierarchy, ERP links, policies,
typed actions and a purpose-built frontend through Core APIs.

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
Channel identity
      │ normalize once
      ▼
Core Identity
      │ configured Identity Sources
      ▼
Business records (customer, retailer, patient, supplier, ...)
```

Core stores canonical identities and generic links. It does not know what a
retailer, patient or supplier is. A business app may register a typed resolver
for hierarchy rules; the resolver is selected by a fixed hook key, never an
arbitrary Python path stored in a database record.

Zero matches stay `Unresolved`, one match is `Resolved`, and multiple matches
are `Ambiguous` for review. Disabled sources deactivate their links on the
next resolution.

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
                                              ├── list/start/read conversations
                                              ├── classify unassigned messages
                                              ├── search and bind exact parties
                                              ├── create a typed case
                                              ├── assign/update conversations
                                              └── queue audited replies/templates
```

Core does not embed an AI model. The stateless endpoint is
`/api/method/frappe_whatsapp_core.mcp_transport.handle`; Frappe API
authentication, Core roles, origin validation, site isolation and an immutable
invocation audit apply before a tool executes.

The Core UI exposes the same boundaries without pretending they are one
monolithic feature:

```text
Core UI
 ├── Shared Inbox   instant chat + reads + topics + assignment + templates
 ├── AI Queue       unclassified messages + manual topic approval
 ├── Polls          question flows + completed-answer counts
 ├── Connectors     installed hooks + flow actions + MCP tools
 ├── Health         event / flow / delivery failures
 └── Settings       Hub onboarding + channel mapping + site inventory
```
