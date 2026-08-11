---
name: whatsapp-core-agent
description: Build and operate audited WhatsApp conversations, visual automations, native Meta Flows, response processing, topic compaction, and Meta Groups through Frappe WhatsApp Core MCP tools. Use when an AI agent must create or publish a flow, connect allowlisted Python business actions, inspect flow responses, read or reply to chats, classify completed conversation segments, or manage WhatsApp resources without accessing Meta directly.
---

# WhatsApp Core Agent

Use only the `whatsapp.*` MCP tools exposed by Frappe WhatsApp Core. Never call Meta Graph directly, bypass Core permissions, or write WhatsApp DocTypes with generic database tools.

## Conversation workflow

1. Read the conversation and its existing topics before acting.
2. Treat inbound messages as immediately available. Delivery, read, and sent statuses may arrive later in a coalesced batch.
3. Send through the typed Core tools such as `whatsapp.send_text`; supply a stable client message id when the tool accepts one so retries do not duplicate messages.
4. Confirm the durable Core message result. Do not repeatedly send merely because a realtime UI event was missed.
5. Never claim that a message was delivered unless the recorded delivery status says so.

## Compact conversation segments

Use `whatsapp.list_unclassified_messages` to find unassigned messages and `whatsapp.list_conversation_topics` to avoid overlapping an existing topic. Group one contiguous intent-to-outcome segment at a time, then call `whatsapp.upsert_topic` with:

- a short intent-based title;
- a factual summary containing the request, material actions, and outcome;
- a business category, confidence, and the exact message ids;
- `Resolved` only when the requested outcome is complete, otherwise the applicable open state;
- `External AI` as the source.

Do not invent an outcome, merge unrelated intents, or hide unresolved work in a resolved topic.

## Visual automation builder

Read [references/flow-builder.md](references/flow-builder.md) before creating or changing an automation.

1. Call `whatsapp.list_flow_actions`; use only a returned dotted method and its parameter schema.
2. Inspect the current graph with `whatsapp.get_automation_flow`, or create a draft with `whatsapp.create_automation_flow`.
3. Build a complete graph with one start, at least one terminal node, valid connections, and bounded cycles. Use `send_flow` to launch a published native Meta Flow and resume from its correlated response.
4. Save the full graph with `whatsapp.save_automation_flow` and resolve every validation error.
5. Call `whatsapp.validate_automation_flow`, then submit it with `whatsapp.request_automation_flow_approval`.
6. A Flow User stops after requesting approval. Only a WhatsApp Manager or System Manager may publish with `confirmation=PUBLISH`.
7. Verify execution with `whatsapp.list_flow_responses`. Treat the response ledger as the durable source of truth.

Never invent an action path, submit a partial graph, publish an invalid draft, or bypass the approval boundary.

## Native Meta Flows

Inspect with `whatsapp.list_flows` and `whatsapp.get_flow`. Create or modify drafts with `whatsapp.create_flow`, `whatsapp.upload_flow_json`, and `whatsapp.update_flow`. Validate the endpoint and public-key state before publishing. Publishing, deprecating, deleting, migrating, or rotating the public key changes external state: summarize the exact target and obtain explicit confirmation first.

Flow responses arrive as durable WhatsApp messages and as centralized Core response records. Read them with `whatsapp.list_flow_responses`, then record the business outcome in the relevant conversation topic. Do not recreate Meta's Flow renderer locally.

## Meta Groups

Inspect groups and activity before changing membership or settings. Use the typed `whatsapp.*group*` tools for creation, updates, invites, join requests, participants, messages, and pins. Confirm the exact group and participants before destructive or membership-changing operations. Never simulate unsupported group behavior with ordinary individual messages.

## Safety and reliability

- Respect WhatsApp User and WhatsApp Manager permissions and team access.
- Treat tool errors and timeouts as unknown outcomes until the durable record is checked.
- Do not expose access tokens, app secrets, webhook signatures, or customer personal data.
- Prefer one bounded action and a verification read over broad bulk mutations.
- Report provider limitations honestly; do not imply that a UI-only feature exists in Meta's API.
