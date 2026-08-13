# Legacy WhatsApp migration

This runbook migrates an Essdee Partners API, SIHMA, or Pasarai Rotary site to
WhatsApp Core. The import is copy-only: it never deletes or updates a legacy
WhatsApp row. Target keys are deterministic, so the command can be rerun after
an interruption without duplicating records.

## Data copied

- WhatsApp accounts into Core channels, without legacy access or verify tokens
- Contacts, normalized identities, conversations, business-party bindings, and
  application-specific contact attributes
- Messages, provider IDs, delivery status, timestamps, media metadata, message
  bodies, failures, legacy source references, and locally cached media files
- Templates, approval state, content/components, buttons, and sync timestamps
- Historical bulk jobs/campaigns and recipients, including personalization,
  result, linked Core message when available, and errors
- Essdee teams and contact assignments. The generated set contains the global
  `Customers`, `Retailers`, and `Salespersons` teams plus per-owner
  `Agent - <name>` and `Retailer - <name>` teams. Generated rows are marked and
  reconciled without deleting manually managed team members or contacts.
- Pasarai AI tags and message tag assignments

Webhook logs, retry queues, pending scheduler work, AI runtime queues, bot model
settings, and credentials are deliberately not copied. Replaying those rows
would resend old work or move transport secrets back into Frappe. Go/Integration
transport credentials must already be configured through the normal Core setup.

The legacy schemas only store a contact-level unread count, not a per-user last
read message. That value cannot be reconstructed accurately. Core per-user read
markers therefore start fresh after cutover.

## Runbook

Replace `<site>` with the target site name.

1. Pause legacy sends and schedulers for the maintenance window, then back up:

   ```bash
   bench --site <site> backup --with-files
   bench --site <site> migrate
   bench --site <site> clear-cache
   ```

2. Preview the registered app migration:

   ```bash
   bench --site <site> execute \
     frappe_whatsapp_core.legacy_migration_runner.preview_installed_legacy_whatsapp
   ```

   Continue only when `migration_ready` is `true` and `blockers` is empty.

3. Run the resumable copy in 500-row message batches:

   ```bash
   bench --site <site> execute \
     frappe_whatsapp_core.legacy_migration_runner.migrate_installed_legacy_whatsapp \
     --kwargs '{"batch_size": 500, "commit_every_batch": 1}'
   ```

   `commit_every_batch=1` checkpoints long message imports. If the process is
   interrupted, run the same command again.

4. Confirm the result has `reconciliation_ok: true`. The reconciliation section
   must show `ok: true` for channels, contacts, messages, media files, templates,
   campaigns, campaign recipients, categories, and category assignments.

5. Rerun the same command once. The second run should report existing records
   rather than new inserts, including `media_files_inserted: 0`, and must still
   return `reconciliation_ok: true`.

6. Smoke-test Core inbox history, one approved template, one new inbound message,
   and one outbound template message before ending the maintenance window.

Do not drop the legacy tables during cutover. Retain them read-only until the
post-migration retention period and business audit are complete.

## Essdee Partner synchronization and team access

When WhatsApp Core is installed, saving an Essdee Partner synchronizes enabled
mapped users with mobile numbers into Core identities and party bindings. The
full generated-team reconciliation is deduplicated on the long queue after the
database commit, so a Partner save does not scan the full hierarchy. Creating,
updating, disabling, or deleting a Partner all schedule the same repair. The
migration can enrich agent/retailer hierarchy from Essdee Sales when that app is
installed; otherwise it uses the business references stored by Partners API.

Core managers can view all contacts and filter the inbox by team. A WhatsApp
User assigned to one or more enabled teams can see only contacts assigned to at
least one of those teams. A user assigned to no team can see only contacts that
also have no enabled team assignment. This rule is enforced by backend document
permissions and inbox APIs; the UI filter is not the security boundary.
