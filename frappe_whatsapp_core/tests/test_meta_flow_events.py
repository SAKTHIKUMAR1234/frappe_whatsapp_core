import json
import unittest

from frappe_whatsapp_core.core_event_handler import _flow_event
from frappe_whatsapp_core.materializer import inbound_message_body


class TestMetaFlowEvents(unittest.TestCase):
	def test_native_flow_response_is_searchable_and_structured(self):
		content = {
			"nfm_reply": {
				"name": "flow",
				"flow_token": "token-1",
				"response_json": json.dumps({"screen": "COMPLETE", "order_id": "ORD-1"}),
			}
		}
		body = inbound_message_body("interactive", content)
		self.assertEqual(body, "Flow submitted · Order Id: ORD-1")
		message = type("Message", (), {
			"name": "MSG-1", "message_type": "interactive", "body": body,
			"channel": "CHANNEL-1",
			"content": json.dumps({"interactive": content}),
		})()
		event = _flow_event(message)
		self.assertTrue(event["meta_flow_response"])
		self.assertEqual(event["flow_response"]["order_id"], "ORD-1")

	def test_rich_message_summaries(self):
		self.assertEqual(inbound_message_body("sticker", {"id": "1"}), "[Sticker]")
		self.assertEqual(inbound_message_body("reaction", {"emoji": "👍"}), "👍")
		self.assertEqual(inbound_message_body("image", {"caption": "Invoice"}), "Invoice")
