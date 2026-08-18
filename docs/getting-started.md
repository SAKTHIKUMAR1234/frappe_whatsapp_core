# WhatsApp Core: getting started

WhatsApp Core is the site-local product used by agents and managers. It does
not store Meta app secrets or run JetStream. Open it from the Frappe Apps page
as **WhatsApp**, or go directly to `/whatsapp`.

## 1. Install and open the product

Install `frappe_whatsapp_core` on every business site that needs the shared
inbox. The app supports Frappe 15 and 16. After `bench migrate` and
`bench build --app frappe_whatsapp_core`, clear the site cache and reload Desk.
The WhatsApp tile appears only for Administrator or a user with a WhatsApp Core
role; selecting it opens `/whatsapp`.

## 2. Assign human roles

- **WhatsApp User** works in the shared inbox and can call contacts within the
  same team scope.
- **WhatsApp Manager** can see all teams and opens management workspaces for
  templates, campaigns, flows, groups, calling, health, and teams.
- **WhatsApp Flow User** may use the approved Flow authoring API but does not
  automatically gain inbox or manager access.

Machine transport roles are not human roles. Use the provisioning action in
Core Settings to create one dedicated non-Desk service identity with
`capability=all`; never reuse Administrator or an agent account.

## 3. Connect the Hub

In **WhatsApp Core Settings**, enter only origins:

- Hub Site URL: `https://whatsapp.example.com`
- Go Relay URL: `https://relay.example.com`

Do not add credentials, `/api/method`, `/webhooks/meta`, query strings, or
fragments. Store the one-time Hub key and secret, map the Hub account to a Core
channel, save, and run the connection check. Core sends outbound work directly
to the Go relay; configuration and template management continue through Hub
APIs.

## 4. Daily shared-inbox behavior

The inbox restores the last read position, fetches older or newer pages only
when needed, and appends realtime Socket.IO messages without reloading the
whole conversation. The conversation list moves the changed chat to the top
with a stable transition. Collapse or pin the labelled navigation using the
button beside the WhatsApp title; the preference is stored only in the
browser.

## 5. Release check

Before traffic, verify:

1. the Apps-page WhatsApp tile opens `/whatsapp` for an agent and is absent for
   a user without a Core role;
2. Core Settings reports Hub, relay, credentials, and account mapping ready;
3. one inbound message appears without a full-page refresh;
4. one outbound text moves from queued to sent/delivered/read as Meta webhooks
   arrive;
5. a user sees only assigned-team and unassigned conversations allowed by the
   documented permission model.

Use [Deployment and operations](deployment-and-operations.md) for the full
production order, migration, rollback, and acceptance procedure.
