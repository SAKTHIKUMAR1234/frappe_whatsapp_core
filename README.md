### Frappe WhatsApp Core

Reusable, configurable WhatsApp business workflow foundation

Supports Frappe **15 and 16** and Python 3.10 or newer.

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

Core manages Meta-hosted WhatsApp Groups, including lifecycle, invite links,
approved invite templates, join approvals, participants, text/media/template
messages, pinned messages and per-participant receipts. It also supports
WhatsApp Business Calling settings, permission requests, call buttons and
templates, deep links, WebRTC signaling, voicemail announcements, opt-in
recording/transcription artifacts and durable call-event logs. Meta's calling
control plane is handled here; audio media runs through the configured WebRTC
or SIP infrastructure.

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
