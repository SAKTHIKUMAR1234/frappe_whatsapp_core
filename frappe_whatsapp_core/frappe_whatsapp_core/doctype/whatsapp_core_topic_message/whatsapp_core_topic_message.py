import frappe
from frappe.model.document import Document


class WhatsAppCoreTopicMessage(Document):
	def validate(self):
		topic_conversation = frappe.db.get_value(
			"WhatsApp Core Conversation Topic",
			self.topic,
			"conversation",
		)
		message_conversation = frappe.db.get_value(
			"WhatsApp Core Message",
			self.message,
			"conversation",
		)
		if topic_conversation != message_conversation:
			frappe.throw("Topic and message must belong to the same conversation")
