# Fresh Essdee Partner directory

Use this procedure only when the business has explicitly chosen to discard its
old WhatsApp conversations and contacts. It does not import a legacy WhatsApp
table or migrate old messages.

1. Stop traffic for the target Core site and take a verified database backup.
2. Review and run `docs/fresh-conversation-reset.sql` against only that site's
   database.
3. Pull and migrate both `frappe_whatsapp_core` and `essdee_partners_api`.
4. Rebuild the contact directory from the current Partner master:

   ```bash
   bench --site sales.essdee.fit execute \
     essdee_partners_api.whatsapp_core_adapter.migration.queue_partner_directory_rebuild \
     --kwargs '{"batch_size":250}'
   ```

5. Wait for the long worker job named
   `essdee-whatsapp-core-partner-directory-rebuild`, then verify the generated
   `Agents`, `Customers`, `Salespersons`, and per-agent teams before resuming
   traffic.

For a phone mapped to several Partner records, the most recently modified
enabled Partner is authoritative. The rebuild updates the one provider-backed
contact presentation and generated assignments; it does not invent a second
WhatsApp recipient.
