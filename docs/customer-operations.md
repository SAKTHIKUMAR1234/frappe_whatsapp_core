# Customer operations workspace

WhatsApp Core v2 treats a WhatsApp identity as a customer record without
changing the canonical identity, message, or team access model. Open
`/whatsapp` to use the workspace.

## Team overview

**Overview** shows only the conversations and teams the signed-in operator is
allowed to access. Its open, unread, unassigned, and active-today metrics are
calculated with the same row-level scope as Shared Inbox. Selecting a team card
opens that team's customer queue directly.

WhatsApp Managers and System Managers see every enabled team. A WhatsApp User
sees only teams where they are an enabled member. Dashboard access never
widens inbox access.

## Personal organization

Every operator has a built-in **Important** collection and may create up to 30
private folders. Open a conversation, show its details, then select Important
or a personal folder under **My folders**. Folder membership is visible only to
that operator and never assigns a team or grants message access.

Use the folder selector to focus the inbox. **All** clears team and personal
folder filters. Folder updates use a user-targeted realtime event, so another
session owned by the same user updates without refreshing the complete inbox.

## Chat and Summary

**Chat** remains the message and call audit record. Each loaded message exposes
team read coverage and the names of responsible operators who have not yet read
it. Existing reader avatars retain their precise read-through timestamp.

**Summary** is a structured customer brief: current intent, categories,
ownership, summary coverage, team visibility, follow-up actions, and risks. It
does not expose raw JSON. Managers may explicitly refresh the AI summary; the
stored message and call history remains authoritative.

## Realtime behavior

The inbox keeps one mounted workspace while switching conversations. New
messages and status changes are applied as targeted Socket.IO deltas rather
than rebuilding the conversation list. Dashboard metrics refresh only while
the Overview route is mounted. Reconnect reconciliation remains responsible
for filling any events missed during a temporary disconnection.

## Upgrade

After pulling the matching release on each Core site, run:

```bash
bench --site <core-site> migrate
bench build --app frappe_whatsapp_core
bench clear-cache
```

No Hub, relay, NATS, Supervisor, or Nginx change is required for this workspace
release. The new folder DocTypes are created by `migrate` and existing
conversations remain unchanged.
