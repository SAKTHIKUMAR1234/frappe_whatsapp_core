-- Destructive one-time reset for a site that will retain WhatsApp account,
-- channel, template, flow definition, workspace, team, and team-member setup.
-- Run only while inbound/outbound processing for the site is stopped and only
-- after taking a verified database backup. Review the counts before COMMIT.

START TRANSACTION;

SELECT 'messages' AS record_type, COUNT(*) AS records
FROM `tabWhatsApp Core Message`
UNION ALL
SELECT 'conversations', COUNT(*) FROM `tabWhatsApp Core Conversation`
UNION ALL
SELECT 'identities', COUNT(*) FROM `tabWhatsApp Core Identity`
UNION ALL
SELECT 'events', COUNT(*) FROM `tabWhatsApp Core Event`;

DELETE FROM `tabWhatsApp Core Flow Step Run`;
DELETE FROM `tabWhatsApp Core Flow Response`;
DELETE FROM `tabWhatsApp Core Flow Instance`;

DELETE FROM `tabWhatsApp Core Topic Message`;
DELETE FROM `tabWhatsApp Core Conversation Topic`;
DELETE FROM `tabWhatsApp Core Message Bookmark`;
DELETE FROM `tabWhatsApp Core Message Category Assignment`;
DELETE FROM `tabWhatsApp Core Message Insight`;
DELETE FROM `tabWhatsApp Core Message Read`;
DELETE FROM `tabWhatsApp Core Conversation Read`;
DELETE FROM `tabWhatsApp Core Group Receipt`;
DELETE FROM `tabWhatsApp Core Campaign Recipient`;
DELETE FROM `tabWhatsApp Core Contact Summary`;
DELETE FROM `tabWhatsApp Core Summary Period`;

UPDATE `tabWhatsApp Core Case`
SET `origin_message` = NULL, `origin_conversation` = NULL;

DELETE FROM `tabWhatsApp Core Call`;
DELETE FROM `tabWhatsApp Core Message`;
DELETE FROM `tabWhatsApp Core Conversation`;

DELETE FROM `tabWhatsApp Core Group Member`;
DELETE FROM `tabWhatsApp Core Group`;

DELETE FROM `tabWhatsApp Core Team Contact`;
DELETE FROM `tabWhatsApp Core Party Binding`;
DELETE FROM `tabWhatsApp Core Identity Link`;
DELETE FROM `tabWhatsApp Core Identity Alias`;
DELETE FROM `tabWhatsApp Core Identity`;

DELETE FROM `tabWhatsApp Core Handler Run`;
DELETE FROM `tabWhatsApp Core Event`;

-- Inspect the affected-row counts above and use ROLLBACK if anything is out
-- of scope. Replace the next statement with ROLLBACK during a dry run.
COMMIT;

-- SQL removes database records only. Frappe File records and physical media
-- files attached to old messages/calls require a separate file-aware cleanup.
