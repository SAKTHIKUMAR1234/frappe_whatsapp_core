app_name = "frappe_whatsapp_core"
app_title = "Frappe WhatsApp Core"
app_publisher = "Essdee"
app_description = "Reusable, configurable WhatsApp business workflow foundation"
app_email = "engineering@essdee.com"
app_license = "mit"

after_install = "frappe_whatsapp_core.setup.ensure_core_setup"
after_migrate = "frappe_whatsapp_core.setup.ensure_core_setup"

# Business applications register handlers here. The base app intentionally
# contains no hospital, manufacturing, sales or Essdee-specific decisions.
whatsapp_core_event_handlers = []

# Business apps map a neutral phone identity onto exact local business records.
whatsapp_core_party_resolvers = []

# Business applications may register one typed resolver per configured source.
# Source documents never contain arbitrary Python paths.
whatsapp_core_identity_resolvers = {}

# External AI and operator tools use business-owned party search adapters;
# Core never imports a sales, hospital or manufacturing module.
whatsapp_core_party_searchers = []

# Company apps can block a Core send with typed business safety rules. They do
# not replace the Core transport or create a second outbound implementation.
whatsapp_core_outbound_preflight = []

# A company app may replace the Core Identity phone at delivery time. Exactly
# one resolver is allowed; returning no value keeps Core's default number.
whatsapp_core_recipient_phone_resolver = []

# Business applications may customize how Core contacts are presented without
# forking the inbox. Hooks receive one batched contact mapping and return
# presentation-only overrides keyed by Core Identity name.
whatsapp_core_contact_presenters = []

# Flow nodes can invoke only registered, typed actions. A builder graph cannot
# execute arbitrary Python, SQL or shell commands.
whatsapp_core_flow_actions = {
	"case.create": "frappe_whatsapp_core.flow_actions.create_case_action",
	"context.set": "frappe_whatsapp_core.flow_actions.set_context_action",
	"topic.upsert": "frappe_whatsapp_core.flow_actions.upsert_topic_action",
}

# Dynamic Meta-hosted Flows call Integration's encrypted endpoint. Integration
# verifies/decrypts the Meta request and calls these Core business handlers with
# ``payload`` and a mapped ``context``. Return None when a handler does not own
# the request; the first dict response wins. Static Meta Flows need no handler.
whatsapp_core_meta_flow_endpoint_handlers = []

# Business apps resolve a prepared Core identity into their own operational
# context and queue one message at a time. Core never imports business modules.
whatsapp_core_campaign_preflight = []
whatsapp_core_campaign_sender = []
whatsapp_core_campaign_batch_sender = []
whatsapp_core_outbound_text_sender = []
whatsapp_core_outbound_template_sender = []

scheduler_events = {
	"cron": {
		"* * * * *": [
			"frappe_whatsapp_core.campaigns.run_due_campaigns",
			"frappe_whatsapp_core.campaigns.refresh_dirty_campaign_counts",
			"frappe_whatsapp_core.dispatcher.retry_stale_events",
			"frappe_whatsapp_core.outbound.retry_queued_messages",
		],
		"*/5 * * * *": [
			"frappe_whatsapp_core.dispatcher.retry_failed_events",
			"frappe_whatsapp_core.campaigns.refresh_active_campaigns",
		],
		"*/30 * * * *": [
			"frappe_whatsapp_core.ai_summaries.queue_pending_summaries",
			"frappe_whatsapp_core.summary_rollups.queue_summary_rollups",
		],
		"15 2 * * *": [
			"frappe_whatsapp_core.summary_rollups.prune_summary_rollups",
		],
	},
}

# Apps
# ------------------

# required_apps = []

# Show WhatsApp beside first-class products such as CRM and Helpdesk. The
# permission method deliberately reuses the same role boundary as the SPA
# bootstrap, so the Apps page cannot advertise a destination the user cannot
# open.
add_to_apps_screen = [
	{
		"name": "frappe_whatsapp_core",
		"logo": "/assets/frappe_whatsapp_core/core_ui/favicon.svg",
		"title": "WhatsApp",
		"route": "/whatsapp",
		"has_permission": "frappe_whatsapp_core.frontend_api.has_app_permission",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/frappe_whatsapp_core/css/frappe_whatsapp_core.css"
# app_include_js = "/assets/frappe_whatsapp_core/js/frappe_whatsapp_core.js"

# include js, css files in header of web template
# web_include_css = "/assets/frappe_whatsapp_core/css/frappe_whatsapp_core.css"
# web_include_js = "/assets/frappe_whatsapp_core/js/frappe_whatsapp_core.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "frappe_whatsapp_core/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "frappe_whatsapp_core/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "frappe_whatsapp_core.utils.jinja_methods",
# 	"filters": "frappe_whatsapp_core.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "frappe_whatsapp_core.install.before_install"
# after_install = "frappe_whatsapp_core.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "frappe_whatsapp_core.uninstall.before_uninstall"
# after_uninstall = "frappe_whatsapp_core.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "frappe_whatsapp_core.utils.before_app_install"
# after_app_install = "frappe_whatsapp_core.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "frappe_whatsapp_core.utils.before_app_uninstall"
# after_app_uninstall = "frappe_whatsapp_core.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "frappe_whatsapp_core.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"WhatsApp Core Conversation": "frappe_whatsapp_core.permissions.conversation_permission_query",
	"WhatsApp Core Message": "frappe_whatsapp_core.permissions.message_permission_query",
	"WhatsApp Core Conversation Read": "frappe_whatsapp_core.permissions.conversation_read_permission_query",
	"WhatsApp Core Message Read": "frappe_whatsapp_core.permissions.message_read_permission_query",
	"WhatsApp Core Team": "frappe_whatsapp_core.permissions.team_permission_query",
	"WhatsApp Core Template": "frappe_whatsapp_core.permissions.template_permission_query",
	"WhatsApp Core Call": "frappe_whatsapp_core.permissions.call_permission_query",
}

has_permission = {
	"WhatsApp Core Conversation": "frappe_whatsapp_core.permissions.has_scoped_conversation_permission",
	"WhatsApp Core Message": "frappe_whatsapp_core.permissions.has_scoped_message_permission",
	"WhatsApp Core Conversation Read": "frappe_whatsapp_core.permissions.has_scoped_conversation_read_permission",
	"WhatsApp Core Message Read": "frappe_whatsapp_core.permissions.has_scoped_message_read_permission",
	"WhatsApp Core Team": "frappe_whatsapp_core.permissions.has_scoped_team_permission",
	"WhatsApp Core Template": "frappe_whatsapp_core.permissions.has_scoped_template_permission",
	"WhatsApp Core Call": "frappe_whatsapp_core.permissions.has_scoped_call_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"frappe_whatsapp_core.tasks.all"
# 	],
# 	"daily": [
# 		"frappe_whatsapp_core.tasks.daily"
# 	],
# 	"hourly": [
# 		"frappe_whatsapp_core.tasks.hourly"
# 	],
# 	"weekly": [
# 		"frappe_whatsapp_core.tasks.weekly"
# 	],
# 	"monthly": [
# 		"frappe_whatsapp_core.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "frappe_whatsapp_core.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "frappe_whatsapp_core.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "frappe_whatsapp_core.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["frappe_whatsapp_core.utils.before_request"]
# after_request = ["frappe_whatsapp_core.utils.after_request"]

# Job Events
# ----------
# before_job = ["frappe_whatsapp_core.utils.before_job"]
# after_job = ["frappe_whatsapp_core.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"frappe_whatsapp_core.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
