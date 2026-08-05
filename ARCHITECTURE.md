# Frappe WhatsApp Core

This app is the complete business-neutral WhatsApp product installed on every
company site. It is not another copy of the Hub.

```text
Meta callback
   │ fast durable enqueue + immediate ACK
   ▼
NATS JetStream (file-backed middleman)
   │ 40 events or 250-millisecond window
   ▼
WhatsApp Core Event (one bulk DB insert + dedupe)
   │ one background batch job
   ├── Essdee adapter
   ├── Hospital adapter
   ├── Manufacturing adapter
   └── Future business adapter
```

Outbound campaigns submit up to 40 independent commands to the relay in one
HTTP request. The relay persists every command as its own JetStream work item,
and workers send them to Meta independently. A second durable callback queue
returns each provider message ID and final send result to Core before later
delivery/read webhooks arrive. Inbound logging is micro-batched. Core owns
identity, party binding, shared inbox, optimistic outbound, conversation,
message, case, campaign, flow, AI queue and MCP contracts. A company app is
optional. When installed, it adds business hierarchy, ERP links, policies,
typed actions and a purpose-built frontend through Core APIs.

## WhatsApp Flows

Customer-facing WhatsApp Flows are native Meta assets. Core manages them
through the Integration Hub and stores only operational events and responses;
it does not render a second, incompatible flow runtime.

```text
Core administrator ──► Integration Hub ──► Meta Flow API
                                               │
Customer completes published Flow ◄───────────┘
                │
                ▼
Meta nfm_reply webhook ──► JetStream ──► Core conversation log
```

Creation, Flow JSON upload, preview, publish, clone, migrate, deprecate and
delete use Meta's API. Native `nfm_reply` responses are materialized into the
conversation log. The previous local automation engine remains disabled by
default for backwards-compatible data access only.

## Groups and calling

Core exposes site-scoped Groups and Calling workspaces while the Integration
Hub owns Meta credentials and Graph API calls. Inbound group messages use an
identity keyed by `group:<META_GROUP_ID>`, so group traffic cannot be merged
with a participant's direct conversation. Calling webhooks are projected into
`WhatsApp Core Call`, with the immutable Core Event retained as the audit
source. Core manages settings, permissions and SDP signaling; WebRTC or SIP
handles the audio media path.

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

Outbound delivery uses the canonical Core Identity phone by default. A company
app may register one `whatsapp_core_recipient_phone_resolver` to derive the
current delivery number from its linked business record. Returning no value
keeps the Core default; multiple registered resolvers are rejected.

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
                      Core batch sender / adapter
                                   │
                       up to 40 per HTTP request
                                   ▼
                  independent durable JetStream items
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
