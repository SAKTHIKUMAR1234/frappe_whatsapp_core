# WhatsApp Core V2 Internal Collaboration — Full Testing Handoff

## 1. Mission

Independently verify the WhatsApp Core V2 conversation collaboration release on a **local development site**. The release adds compact conversation summaries, private internal work items, message/summary references, mentions, assignments, replies, resolution state, durable notifications, and permission-scoped realtime updates.

The tester must find defects, reproduce them, and report evidence. The tester must **not** deploy, push, commit, rewrite history, use production credentials, or modify production.

## 2. Repository state and safety boundary

| Item | Value |
| --- | --- |
| Bench | `/mnt/storage/dev/frappe-v15` |
| App | `/mnt/storage/dev/frappe-v15/apps/frappe_whatsapp_core` |
| Suggested local site | `sales-prod.site` (despite its name, this is in the local bench) |
| Browser route | `/whatsapp#/inbox/<conversation>` |
| Current branch when handed off | `feature/whatsapp-platform-production` |
| Current baseline commit | `82898ef` |
| Date of handoff | 2026-08-26 |

### Critical dirty-worktree warning

The app worktree contains a broad, uncommitted V2 change set. The internal collaboration feature is only part of it. Existing changes belong to the user.

Do not run any of the following:

```text
git reset
git checkout -- <path>
git restore <path>
git clean
git stash
git commit
git push
```

Read-only Git inspection is permitted. Building assets and creating test data on the **local** site are permitted for testing.

Before testing, capture but do not alter the state:

```bash
cd /mnt/storage/dev/frappe-v15/apps/frappe_whatsapp_core
git status --short
git branch --show-current
git rev-parse --short HEAD
git diff --check
```

## 3. Product contract to verify

### 3.1 Compact and expanded conversation views

- A conversation with a contact summary or conversation topics opens in compact summary mode by default.
- A conversation without summarization data opens in chat mode.
- The operator can switch between summary and chat views.
- The operator's choice is stored per conversation under `whatsapp:conversation-view:<conversation>`.
- Switching views must not reload the entire inbox, lose the selected conversation, or break realtime updates.

### 3.2 Private internal work items

An operator can create a private internal note inside a conversation. A note may contain:

- Plain-text content.
- Up to 50 message references from the same conversation.
- One supported summary reference from the same conversation/identity.
- Up to 20 mentioned users who are eligible for that conversation.
- One eligible assignee.
- A parent note when the note is a reply.
- `Open` or `Resolved` state.

These notes are internal Core data. They must never be sent to Meta or shown to the external WhatsApp contact.

### 3.3 Collaboration lifecycle

The supported lifecycle is:

1. Open a permission-visible conversation.
2. Select messages or a summary as context.
3. Add an internal note.
4. Optionally mention and/or assign an eligible teammate.
5. The teammate receives a durable Frappe Notification Log entry and a realtime notification refresh.
6. The teammate opens the notification and lands on the correct conversation/note.
7. A permitted operator replies, edits, resolves, reopens, or deletes the work item.
8. Every visible client in the same permission scope receives the incremental realtime change without a full inbox reload.

### 3.4 Authorization contract

- Core access roles are `System Manager`, `WhatsApp Manager`, and `WhatsApp User`.
- `System Manager` and `WhatsApp Manager` have management scope.
- Other Core users must pass the existing conversation/team/contact/assignment scope.
- Mentions and assignments are limited to users returned by the conversation recipient scope.
- Only the author, current assignee, or a management-role user may mutate/delete a work item.
- Message references must belong to the work item's conversation.
- Replies must target a note in the same conversation.
- Summary references must belong to the same conversation or remote identity.
- Notification queries must return only the current user's notifications and must re-check current conversation access.
- Realtime payloads must be sent to eligible Frappe user rooms, never broadcast as protected data to the whole site.

## 4. Architecture and data flow

```text
Inbox UI
  |-- compact/chat view preference -> browser localStorage (per conversation)
  |-- create/update/delete note ----> whitelisted Core API
                                         |
                                         |-- require Core role
                                         |-- assert conversation access
                                         |-- validate references/mentions/assignee
                                         |-- persist WhatsApp Core Internal Comment
                                         |-- enqueue Frappe Notification Log
                                         `-- publish permission-scoped realtime delta
                                                         |
                                                         `-> eligible user Socket.IO rooms

AppShell notification bell
  |-- reads current user's durable collaboration notifications
  `-- deep-links to /whatsapp#/inbox/<conversation>?comment=<comment>
```

No Hub code is required for this feature. The Hub remains responsible for Meta transport; internal collaboration remains private to Core.

## 5. Data model

DocType: `WhatsApp Core Internal Comment`

| Field | Purpose |
| --- | --- |
| `conversation` | Parent Core conversation |
| `user` | Author |
| `content` | Internal note text |
| `message_references` | JSON list of Core message names |
| `reference_doctype` / `reference_name` | Dynamic summary/topic reference |
| `parent_comment` | Threaded reply target |
| `mentioned_users` | JSON list of mentioned user IDs |
| `assigned_to` | Current assignee |
| `status` | `Open` or `Resolved` |
| `resolved_by` / `resolved_at` | Resolution audit fields |

Supported summary reference DocTypes:

- `WhatsApp Core Conversation Topic`
- `WhatsApp Core Contact Summary`
- `WhatsApp Core Summary Period`

Backend limits:

- Comment page: 30 by default, 100 maximum.
- Referenced messages: 50 maximum.
- Mentions: 20 maximum.
- UI note length: 2,000 characters.

## 6. Public API and realtime contract

Module: `frappe_whatsapp_core.internal_comments`

| Method | Expected result |
| --- | --- |
| `comment_page` | Permission-scoped cursor page of enriched comments |
| `work_item_assignees` | Enabled users eligible for this conversation |
| `add_comment` | Creates and returns an enriched work item |
| `update_comment` | Updates content, references, assignee, mentions, or status |
| `delete_comment` | Deletes an authorized work item |
| `collaboration_notifications` | Current user's accessible durable notifications |
| `mark_collaboration_notification_read` | Marks only the current user's notification read |

Realtime event: `whatsapp_core_internal_comment`

Expected payload:

```json
{
  "conversation": "<conversation-name>",
  "status": "created | updated | deleted",
  "comment": { "name": "<comment-name>" }
}
```

The actual comment projection includes display names, avatars, message previews, summary label, parent preview, mentions, assignee, and lifecycle fields.

## 7. Primary implementation map

### Backend

- `frappe_whatsapp_core/internal_comments.py`
- `frappe_whatsapp_core/realtime.py`
- `frappe_whatsapp_core/permissions.py`
- `frappe_whatsapp_core/inbox.py`
- `frappe_whatsapp_core/frappe_whatsapp_core/doctype/whatsapp_core_internal_comment/whatsapp_core_internal_comment.json`
- `frappe_whatsapp_core/frappe_whatsapp_core/doctype/whatsapp_core_internal_comment/whatsapp_core_internal_comment.py`

### Frontend

- `core_ui/src/features/inbox/views/InboxView.vue`
- `core_ui/src/features/inbox/components/InternalCommentsPanel.vue`
- `core_ui/src/features/inbox/components/ConversationSummaryPanel.vue`
- `core_ui/src/features/inbox/components/ConversationHeader.vue`
- `core_ui/src/features/inbox/components/MessageActionMenu.vue`
- `core_ui/src/features/inbox/utils/conversationView.js`
- `core_ui/src/layouts/AppShell.vue`

### Tests

- `frappe_whatsapp_core/tests/test_team_contact_access.py`
- `frappe_whatsapp_core/tests/test_contracts.py`
- `frappe_whatsapp_core/tests/test_workspace_api.py`
- `core_ui/src/features/inbox/utils/conversationView.test.js`

## 8. Local preparation

Do not copy production configuration or credentials. Use only the existing local bench and synthetic users/data.

```bash
cd /mnt/storage/dev/frappe-v15

# Confirm the app is installed on the local test site.
bench --site sales-prod.site list-apps | grep -Fx frappe_whatsapp_core

# Apply the current local schema only if the local site is not already migrated.
bench --site sales-prod.site migrate

# Build the current local UI.
bench build --app frappe_whatsapp_core
```

Start the local development processes in a separate terminal when browser testing is required:

```bash
cd /mnt/storage/dev/frappe-v15
bench start
```

Do not record administrator passwords, API keys, tokens, cookies, TURN credentials, Meta credentials, or site configuration in test evidence.

## 9. Automated verification

### 9.1 Backend targeted suite

This module contains 24 tests and covers team scope, internal work items, references, mentions, assignments, durable notifications, realtime scope, presence, messages, and calls.

```bash
cd /mnt/storage/dev/frappe-v15
bench --site sales-prod.site run-tests \
  --app frappe_whatsapp_core \
  --module frappe_whatsapp_core.tests.test_team_contact_access
```

Expected: **24 passed, 0 failed**.

### 9.2 Full backend suite

```bash
cd /mnt/storage/dev/frappe-v15
bench --site sales-prod.site run-tests --app frappe_whatsapp_core
```

Recorded result before handoff: **426 passed, 0 failed**. The new tester must run it again and report the new count rather than copying this result.

### 9.3 Frontend unit suite

```bash
cd /mnt/storage/dev/frappe-v15/apps/frappe_whatsapp_core/core_ui
yarn test:unit
```

Recorded result before handoff: **43 passed, 0 failed**.

### 9.4 Formatting and production build

```bash
cd /mnt/storage/dev/frappe-v15/apps/frappe_whatsapp_core/core_ui
yarn format:check
yarn build
```

Recorded build before handoff: **2,054 modules transformed**. A new tester must preserve the complete command output and exit codes.

### 9.5 Static integrity

```bash
cd /mnt/storage/dev/frappe-v15/apps/frappe_whatsapp_core
git diff --check
rg -n "console\.(log|debug)|debugger" core_ui/src frappe_whatsapp_core
```

Debug-search matches must be reviewed; the command alone is not a failure.

## 10. Required synthetic test topology

Create or reuse local-only records with a distinctive `V2-TEST-` prefix:

- One WhatsApp Manager.
- Team A with Member A and Member B.
- Team B with Member C.
- One Core user with no team, if the existing unassigned-chat behavior is tested.
- One outsider who has no access to Team A's conversation.
- One Team A conversation with at least 35 messages and a contact summary/topic.
- One Team B conversation.
- One unassigned conversation.
- At least 35 internal notes to exercise comment pagination.

Use separate browser contexts for Manager, Member A, Member B, Member C, and Outsider. Do not impersonate production users.

## 11. Browser acceptance matrix

For every case, record browser, viewport, user role, conversation, steps, expected result, actual result, console output, network failures, and a screenshot or trace.

### A. View behavior

| ID | Test | Expected |
| --- | --- | --- |
| VIEW-01 | Open summarized conversation | Compact summary opens by default |
| VIEW-02 | Open conversation without summary/topics | Chat opens by default |
| VIEW-03 | Switch compact -> chat -> another route -> back | Choice persists for that conversation |
| VIEW-04 | Switch between two conversations with different saved modes | Each conversation retains its own mode |
| VIEW-05 | Navigate away from Inbox and return without hard refresh | Inbox mounts correctly; no blank UI or duplicated request storm |
| VIEW-06 | Switch mode while a realtime message arrives | Message delta remains correct; no full-list rebuild |

### B. Internal note creation and references

| ID | Test | Expected |
| --- | --- | --- |
| NOTE-01 | Create plain internal note | Appears once, remains after refresh, never appears as WhatsApp message |
| NOTE-02 | Select one message and create note | Note shows one human-readable message preview, not a random ID |
| NOTE-03 | Select multiple messages | Correct count/previews; selected state clears after save |
| NOTE-04 | Link contact/topic/period summary | Human-readable summary label appears |
| NOTE-05 | Create reply | Parent author and parent preview appear; composer focuses automatically |
| NOTE-06 | Add 2,000-character note | Accepted and rendered without layout overflow |
| NOTE-07 | Empty/whitespace note | Submit remains blocked |
| NOTE-08 | 51 message references through direct API | Rejected with validation error |
| NOTE-09 | Cross-conversation message/summary/reply reference | Rejected; no document created |

### C. Assignment, mentions, and notification

| ID | Test | Expected |
| --- | --- | --- |
| COLLAB-01 | Member A opens assignee/mention controls | Only eligible enabled users are shown |
| COLLAB-02 | Assign Member B | Member B receives one durable notification and realtime bell update |
| COLLAB-03 | Mention Member B and Member C where C is out of scope | API rejects out-of-scope mention; no leakage |
| COLLAB-04 | Assign and mention same user | No duplicate notification |
| COLLAB-05 | Update note with a newly added recipient | Only newly added recipient is notified |
| COLLAB-06 | Reply to Member A's note | Parent author is notified unless they are the acting user |
| COLLAB-07 | Refresh Member B's page | Unread notification persists through Notification Log |
| COLLAB-08 | Open notification | Opens correct conversation and focuses correct note; notification becomes read |
| COLLAB-09 | Attempt to mark another user's notification read | Rejected/not found |

### D. Lifecycle and permissions

| ID | Test | Expected |
| --- | --- | --- |
| LIFE-01 | Author edits own note | Updated once across open clients |
| LIFE-02 | Assignee resolves and reopens | State and audit fields update; realtime clients match |
| LIFE-03 | Unrelated permitted viewer edits/deletes note | Rejected unless user is manager |
| LIFE-04 | Manager edits/deletes note | Allowed |
| LIFE-05 | Outsider calls list/add/update/delete APIs directly | Permission error; no row/payload leakage |
| LIFE-06 | User loses team access after notification is created | Notification feed no longer returns inaccessible item |
| LIFE-07 | Delete note in one session | Removed once in other session without full reload |

### E. Pagination and concurrency

| ID | Test | Expected |
| --- | --- | --- |
| PAGE-01 | Load a conversation with >30 notes | First page ordered correctly and indicates more |
| PAGE-02 | Load older notes | No duplicates/gaps; stable cursor ordering by creation/name |
| PAGE-03 | Request limit 0, negative, and >100 | Server clamps to supported range |
| PAGE-04 | Two users edit/resolve close together | Final state is consistent; UI does not duplicate cards |
| PAGE-05 | Reconnect Socket.IO after temporary disconnect | Durable state reloads and subsequent realtime deltas apply once |

### F. Responsive, keyboard, and accessibility

Test at minimum:

- 390 x 844 mobile.
- 768 x 1024 tablet.
- 1366 x 768 desktop.
- 1920 x 1080 desktop.

Verify:

- No horizontal page overflow.
- Composer, assignee, mentions, note actions, and notification popover remain usable.
- Keyboard focus is visible.
- `Ctrl/Cmd + Enter` submits a valid note.
- Reply moves focus to the internal note field.
- Icon-only actions have accessible names.
- Popovers remain open while moving the pointer into them.
- Escape/cancel behavior does not discard unrelated state.
- Light and dark themes maintain readable contrast.
- Browser console contains zero uncaught errors and ideally zero warnings.

### G. Regression smoke tests

- Open/close/switch conversations without reloading all list data.
- Receive a new message and verify incremental chat/list update.
- Send a normal message and confirm it is not confused with an internal note.
- Load older/newer messages and preserve read position.
- Search/filter conversations.
- Open media preview and return to the chat.
- Navigate through Dashboard, Inbox, Templates, Teams, Settings, then back to Inbox.
- Verify the notification bell does not call its API when the Inbox module is unavailable.
- Verify standard Frappe login redirection and logout still work.

## 12. Direct API abuse tests

Use an authenticated local test user's session and Frappe's normal RPC boundary. Do not bypass decorators by calling `.__wrapped__` when assessing security.

Test malformed inputs:

- Nonexistent conversation/comment/message/summary.
- Cross-conversation references.
- Invalid JSON strings for mentions/references.
- Duplicate mentions and references.
- More than 20 mentions.
- More than 50 message references.
- Invalid status.
- Disabled or out-of-scope assignee.
- HTML/script-looking text in note content.
- Another user's notification name.

Expected: validation/permission errors are controlled, no stack trace or protected row is exposed to the browser, no partial record remains, and rendered note content is escaped.

## 13. Performance observations

Capture measurements; do not claim performance from visual impression.

- Network request count when opening Inbox.
- Network request count when switching one conversation.
- Request count for one realtime create/update/delete event.
- Time to render 30 and 100 internal notes.
- Time and query count for `comment_page` with at least 1,000 synthetic notes if practical.
- Browser main-thread long tasks while switching summary/chat.
- Memory before and after switching between 50 conversations.

Acceptance intent:

- Realtime changes are incremental.
- No whole-inbox refetch is triggered by an internal note delta.
- Comment pagination remains bounded.
- No obvious listener/subscription duplication appears after route changes.

## 14. Evidence already available

These artifacts demonstrate the prior implementation run; they do not replace independent testing:

- `docs/internal-collaboration-release.html`
- `/mnt/storage/dev/frappe-v15/output/playwright/whatsapp-compact-summary-final.png`
- `/mnt/storage/dev/frappe-v15/output/playwright/whatsapp-internal-collaboration-final.png`
- `/mnt/storage/dev/frappe-v15/output/playwright/internal-collaboration-release-report.png`

Prior browser verification covered compact summary, summary-linked note creation, mention, assignment, reply, resolution, durable Notification Log creation, and zero observed console errors/warnings.

## 15. Required tester deliverables

Return all of the following:

1. Environment details: OS, browser/version, viewport, branch, baseline commit, and local site.
2. Exact commands and exit codes.
3. Automated results with passed/failed/skipped counts and duration.
4. Completed acceptance matrix with pass/fail for every ID.
5. Screenshots for the main happy path and every defect.
6. Browser console and failed-network-request report.
7. Realtime two-session proof.
8. Permission/IDOR proof using synthetic users.
9. Performance measurements.
10. Defects ranked as blocker, high, medium, or low.
11. A final release verdict: `PASS`, `PASS WITH KNOWN ISSUES`, or `FAIL`.

For each defect, use:

```text
Title:
Severity:
Test ID:
Environment:
Preconditions:
Steps:
Expected:
Actual:
Console/network evidence:
Screenshot/trace path:
Likely code area:
Regression risk:
```

## 16. Release exit criteria

The feature is ready only when:

- Targeted 24-test backend module passes.
- Full Core backend suite passes.
- Frontend unit suite and production build pass.
- All blocker/high acceptance cases pass.
- Two-session realtime create/update/delete and durable notification tests pass.
- All direct API scope/IDOR tests pass.
- Mobile, tablet, and desktop flows are usable.
- No protected data leaks through API, notification, or Socket.IO.
- No internal note is sent to the WhatsApp contact or Hub/Meta transport.
- No uncaught browser error remains.
- The tester provides a clear evidence-backed release verdict.

## 17. Scope boundary for the testing AI

This handoff authorizes **testing and reporting**, not broad implementation, Git publication, or production changes. If a defect is found, first produce a minimal reproduction and identify the likely source. Do not silently patch it unless the user separately authorizes fixes.

