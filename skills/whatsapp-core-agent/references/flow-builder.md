# Flow Builder Contract

## Graph shape

Use schema version `1` with `triggers`, `nodes`, and `edges`. Node ids and edge ids must be unique.

Required structure:

- exactly one `start` node;
- at least one `end` or `human_handoff` node;
- every non-terminal node has an outgoing edge;
- every node is reachable from `start`;
- loops have `max_traversals` on an edge in the cycle;
- conditional nodes have at least two branches and one default branch.

Prefer the unified `ask_input` node. Supported input types are `text`, `number`, `radio`, `select`, and `attachment`; attachments may allow `image`, `document`, `audio`, and `video`. Legacy `ask_text` and `ask_choice` nodes remain readable. Other nodes are `start`, `send_template`, `send_message`, `send_flow`, `condition`, `action`, `wait`, `human_handoff`, and `end`.

One contact may have only one active custom Flow. `/exit`, `/cancel`, or `/stop` closes it. While an automatic action is running, extra replies receive a bounded wait response instead of starting another Flow.

Triggers support `command`, `template_button`, `inbound_pattern`, `case_event`, `schedule`, and `api`. Commands match the leading command, so `/survey 123` starts a `/survey` trigger while the complete inbound body remains in context. Button and inbound patterns support wildcards.

## Variables

Reference runtime values with `{"var":"answers.field"}` in API graphs. The visual UI shows the same value as `{{answers.field}}`.

Common paths:

- `answers.<answer_key>` for chat questions;
- `responses.<response_key>` for a submitted native Meta Flow;
- `actions.<output_key>` for an earlier action result;
- `inputs.<answer_key>` for normalized typed input metadata;
- `last_input` for the most recent normalized input;
- `attachments` for durable private File references collected by the Flow;
- `inbound.*` for the triggering message.

Use `config.options_from={\"var\":\"actions.lookup.options\"}` on a radio/select input to populate its choices from an earlier action. Use bounded cycle edges for an “attach another?” loop.

## Python actions

Call `whatsapp.list_flow_actions`. Each item returns a stable key, dotted `method`, label, and JSON parameter schema. Put the returned dotted method in `config.action`. Provide only declared parameters in `config.input`.

An installed app registers actions in hooks:

```python
whatsapp_core_flow_actions = {
    "support.create_ticket": {
        "label": "Create support ticket",
        "method": "my_app.whatsapp_actions.create_ticket",
        "parameters": {
            "type": "object",
            "required": ["subject"],
            "properties": {
                "subject": {"type": "string", "title": "Subject"},
                "details": {"type": "object", "title": "Submitted details"},
            },
            "additionalProperties": False,
        },
    },
}
```

The handler may accept `action_input`, `context`, `flow_instance`, `flow_response`, and `flow_payload`. The stable `flow_payload` contains flow/version/instance/conversation identifiers plus `action_input`, `last_input`, `answers`, `inputs`, and `attachments`. Attachment values contain the source message, media type, private Frappe File name, and file URL; S3 continues through the normal File lifecycle. A dotted path not present in this installed catalog is rejected even if the function exists.

Return JSON-safe data and save it under the action node's `output_key`. Add an explicit `send_message` node using `{{actions.<output_key>.message}}` when Core should send the action response. This keeps outbound behavior visible in the graph.

## Launching a native Meta Flow

A `send_flow` node requires:

- `flow_id`: published Meta Flow id;
- `flow_action`: `navigate` or `data_exchange`;
- `screen`: required for `navigate`;
- `response_key`: where the correlated submission is stored;
- optional message, CTA, and initial data.

Core creates a unique flow token, queues the native interactive message, waits, correlates the inbound `nfm_reply`, stores it in the response ledger, and resumes the graph. Do not reuse or fabricate the token.

## Native data-exchange actions

To call an allowlisted business action from a native Meta Flow data exchange, send `_core_action` and `_core_params` in the decrypted Flow data object. The action must be in `whatsapp.list_flow_actions`. Core validates its input, executes it, records the request/response/action result, and returns the next screen payload.

## AI workflow

1. Discover actions and existing flows.
2. Create or read a draft.
3. Build and save the complete graph.
4. Validate until `errors` is empty.
5. Submit with `whatsapp.request_automation_flow_approval` and present a concise impact summary.
6. Stop if operating as a WhatsApp Flow User. A Manager may publish with `confirmation=PUBLISH` after review.
7. Inspect `whatsapp.list_flow_responses` and relevant conversation messages.

Publishing is an external behavioral change. Never infer approval from a request to draft, validate, explain, or test.
