<script setup>
import { Background } from "@vue-flow/background";
import { VueFlow, useVueFlow } from "@vue-flow/core";
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import FlowNode from "./FlowNode.vue";

const props = defineProps({ flowName: String, page: Object });
const {
	addEdges,
	addNodes,
	findNode,
	fitView,
	onConnect,
	onEdgeClick,
	onNodeClick,
	project,
	removeEdges,
	removeNodes,
} = useVueFlow();

const palette = [
	["send_template", "Template"],
	["send_message", "Message"],
	["ask_text", "Ask Text"],
	["ask_choice", "Ask Choice"],
	["condition", "Branch"],
	["action", "Action / Connector"],
	["wait", "Wait"],
	["human_handoff", "Human Handoff"],
	["end", "End"],
];

const graph = reactive({ schema_version: 1, triggers: [], nodes: [], edges: [] });
const elements = ref([]);
const selected = ref(null);
const errors = ref([]);
const loading = ref(true);
let nodeCounter = 0;
let edgeCounter = 0;

const selectedNode = computed(() =>
	selected.value?.kind === "node" ? findNode(selected.value.id) : null
);
const nodeConfigJson = ref("{}");
const edgeConditionJson = ref("{}");
const triggersJson = ref("[]");

onConnect((connection) => {
	const edge = {
		id: `edge-${++edgeCounter}`,
		...connection,
		type: "smoothstep",
		data: {},
	};
	addEdges([edge]);
});

onNodeClick(({ node }) => {
	selected.value = { kind: "node", id: node.id };
	nodeConfigJson.value = JSON.stringify(node.data.config || {}, null, 2);
});

onEdgeClick(({ edge }) => {
	selected.value = { kind: "edge", id: edge.id, edge };
	edgeConditionJson.value = JSON.stringify(edge.data?.when || {}, null, 2);
});

function dragStart(event, type) {
	event.dataTransfer.setData("application/whatsapp-flow-node", type);
	event.dataTransfer.effectAllowed = "move";
}

function drop(event) {
	const type = event.dataTransfer.getData("application/whatsapp-flow-node");
	if (!type) return;
	const bounds = event.currentTarget.getBoundingClientRect();
	const position = project({ x: event.clientX - bounds.left, y: event.clientY - bounds.top });
	const id = `${type}-${++nodeCounter}`;
	const node = {
		id,
		type: "flow",
		position,
		data: {
			type,
			label: palette.find((item) => item[0] === type)?.[1] || type,
			config: defaultConfig(type),
		},
	};
	addNodes([node]);
	nextTick(() => {
		selected.value = { kind: "node", id };
		nodeConfigJson.value = JSON.stringify(node.data.config, null, 2);
	});
}

function defaultConfig(type) {
	if (type === "send_template") return { label: "Template", template: "" };
	if (type === "send_message") return { label: "Message", message: "" };
	if (type === "ask_text")
		return { label: "Ask Text", message: "", answer_key: "", required: true };
	if (type === "ask_choice")
		return {
			label: "Ask Choice",
			message: "",
			answer_key: "",
			options: [
				{ label: "Yes", value: "yes" },
				{ label: "No", value: "no" },
			],
		};
	if (type === "action") return { label: "Action", action: "", input: {} };
	if (type === "wait") return { label: "Wait", resume_on: "event" };
	if (type === "human_handoff") return { label: "Human Handoff", reason: "" };
	return { label: palette.find((item) => item[0] === type)?.[1] || type };
}

function applyNodeConfig() {
	try {
		const config = JSON.parse(nodeConfigJson.value || "{}");
		selectedNode.value.data.config = config;
		selectedNode.value.data.label = config.label || selectedNode.value.data.type;
		frappe.show_alert({ message: __("Node updated"), indicator: "green" });
	} catch (error) {
		frappe.throw(__("Node configuration must be valid JSON"));
	}
}

function applyEdgeCondition() {
	try {
		const condition = JSON.parse(edgeConditionJson.value || "{}");
		const edge = elements.value.find((item) => item.id === selected.value.id);
		edge.data = edge.data || {};
		if (Object.keys(condition).length) edge.data.when = condition;
		else delete edge.data.when;
		frappe.show_alert({ message: __("Branch updated"), indicator: "green" });
	} catch (error) {
		frappe.throw(__("Branch condition must be valid JSON"));
	}
}

function markDefaultEdge() {
	const edge = elements.value.find((item) => item.id === selected.value.id);
	edge.data = edge.data || {};
	edge.data.default = !edge.data.default;
}

function applyTriggers() {
	try {
		const triggers = JSON.parse(triggersJson.value || "[]");
		if (!Array.isArray(triggers)) throw new Error("Triggers must be a list");
		graph.triggers = triggers;
		frappe.show_alert({ message: __("Triggers updated"), indicator: "green" });
	} catch (error) {
		frappe.throw(__("Triggers must be a valid JSON list"));
	}
}

function deleteSelected() {
	if (!selected.value) return;
	if (selected.value.kind === "node") removeNodes([selected.value.id]);
	else removeEdges([selected.value.id]);
	selected.value = null;
}

function serialize() {
	const nodes = elements.value
		.filter((item) => item.type === "flow")
		.map((node) => ({
			id: node.id,
			type: node.data.type,
			position: node.position,
			config: node.data.config || {},
		}));
	const edges = elements.value
		.filter((item) => item.source && item.target)
		.map((edge) => ({
			id: edge.id,
			source: edge.source,
			target: edge.target,
			...(edge.data?.when ? { when: edge.data.when } : {}),
			...(edge.data?.default ? { default: true } : {}),
			...(edge.data?.max_traversals
				? { max_traversals: edge.data.max_traversals }
				: {}),
		}));
	return {
		schema_version: 1,
		triggers: graph.triggers,
		nodes,
		edges,
	};
}

async function save() {
	frappe.dom.freeze(__("Saving flow..."));
	try {
		const response = await frappe.call({
			method: "frappe_whatsapp_core.flow_api.save_draft",
			args: { flow_name: props.flowName, graph: serialize() },
		});
		errors.value = response.message.errors || [];
		frappe.show_alert({ message: __("Draft saved"), indicator: "green" });
	} finally {
		frappe.dom.unfreeze();
	}
}

async function validate() {
	await save();
	if (errors.value.length) {
		frappe.msgprint({
			title: __("Flow needs attention"),
			message: `<ul>${errors.value.map((error) => `<li>${frappe.utils.escape_html(error)}</li>`).join("")}</ul>`,
			indicator: "orange",
		});
	} else {
		frappe.show_alert({ message: __("Flow is valid"), indicator: "green" });
	}
}

async function publish() {
	await save();
	if (errors.value.length) {
		frappe.throw(__("Fix validation errors before publishing"));
	}
	const response = await frappe.call({
		method: "frappe_whatsapp_core.flow_api.publish",
		args: { flow_name: props.flowName },
		freeze: true,
		freeze_message: __("Publishing immutable version..."),
	});
	frappe.msgprint(
		__("Published version {0}", [response.message.version]),
		__("Flow Published")
	);
}

async function load() {
	const response = await frappe.call({
		method: "frappe_whatsapp_core.flow_api.get_builder",
		args: { flow_name: props.flowName },
	});
	const incoming = response.message.graph;
	Object.assign(graph, incoming);
	triggersJson.value = JSON.stringify(incoming.triggers || [], null, 2);
	errors.value = response.message.errors || [];
	nodeCounter = incoming.nodes.length;
	edgeCounter = incoming.edges.length;
	elements.value = [
		...incoming.nodes.map((node) => ({
			id: node.id,
			type: "flow",
			position: node.position || { x: 0, y: 0 },
			data: {
				type: node.type,
				label: node.config?.label || node.type,
				config: node.config || {},
			},
		})),
		...incoming.edges.map((edge) => ({
			id: edge.id,
			source: edge.source,
			target: edge.target,
			type: "smoothstep",
			data: {
				...(edge.when ? { when: edge.when } : {}),
				...(edge.default ? { default: true } : {}),
				...(edge.max_traversals ? { max_traversals: edge.max_traversals } : {}),
			},
		})),
	];
	loading.value = false;
	nextTick(() => setTimeout(() => fitView({ padding: 0.12, maxZoom: 1 }), 600));
}

onMounted(() => {
	props.page.set_primary_action(__("Save Draft"), save);
	props.page.add_button(__("Validate"), validate);
	props.page.add_button(__("Publish"), publish);
	load();
});
</script>

<template>
	<div v-if="loading" class="builder-loading">{{ __("Loading flow...") }}</div>
	<div v-else class="flow-builder">
		<aside class="palette">
			<h6>{{ __("Nodes") }}</h6>
			<div
				v-for="[type, label] in palette"
				:key="type"
				class="palette-item"
				draggable="true"
				@dragstart="dragStart($event, type)"
			>
				{{ __(label) }}
			</div>
			<div class="hint">{{ __("Drag a node onto the canvas, then connect the dots.") }}</div>
		</aside>

		<main class="canvas" @dragover.prevent @drop="drop">
			<VueFlow v-model="elements" :delete-key-code="null" connection-mode="loose">
				<Background pattern-color="#cbd5e1" :gap="18" />
				<template #node-flow="nodeProps">
					<FlowNode :data="nodeProps.data" />
				</template>
			</VueFlow>
		</main>

		<aside class="properties">
			<template v-if="selected?.kind === 'node'">
				<h6>{{ __("Node Configuration") }}</h6>
				<textarea v-model="nodeConfigJson" rows="18" class="form-control code"></textarea>
				<button class="btn btn-primary btn-sm mt-3" @click="applyNodeConfig">
					{{ __("Apply") }}
				</button>
				<button class="btn btn-default btn-sm mt-3 ml-2" @click="deleteSelected">
					{{ __("Delete") }}
				</button>
			</template>
			<template v-else-if="selected?.kind === 'edge'">
				<h6>{{ __("Branch Condition") }}</h6>
				<textarea v-model="edgeConditionJson" rows="12" class="form-control code"></textarea>
				<button class="btn btn-primary btn-sm mt-3" @click="applyEdgeCondition">
					{{ __("Apply") }}
				</button>
				<button class="btn btn-default btn-sm mt-3 ml-2" @click="markDefaultEdge">
					{{ __("Toggle Default") }}
				</button>
				<button class="btn btn-default btn-sm mt-3 ml-2" @click="deleteSelected">
					{{ __("Delete") }}
				</button>
			</template>
			<template v-else>
				<h6>{{ __("Flow Triggers") }}</h6>
				<textarea v-model="triggersJson" rows="12" class="form-control code"></textarea>
				<button class="btn btn-primary btn-sm mt-3" @click="applyTriggers">
					{{ __("Apply Triggers") }}
				</button>
				<hr />
				<h6>{{ __("How it works") }}</h6>
				<p class="text-muted">
					{{ __("Select a node or connection to configure it. Drafts are validated before an immutable version can be published.") }}
				</p>
				<div v-if="errors.length" class="validation">
					<strong>{{ __("{0} validation issue(s)", [errors.length]) }}</strong>
					<ul><li v-for="error in errors" :key="error">{{ error }}</li></ul>
				</div>
			</template>
		</aside>
	</div>
</template>

<style lang="scss" scoped>
@import "@vue-flow/core/dist/style.css";
@import "@vue-flow/core/dist/theme-default.css";

.flow-builder {
	display: grid;
	grid-template-columns: 210px minmax(500px, 1fr) 300px;
	gap: 10px;
	height: calc(100vh - var(--navbar-height) - var(--page-head-height) - 55px);
}
.palette,
.properties,
.canvas {
	border: 1px solid var(--border-color);
	border-radius: var(--border-radius-lg);
	background: var(--fg-color);
	overflow: auto;
}
.palette,
.properties {
	padding: 16px;
}
.palette-item {
	padding: 9px 11px;
	margin: 7px 0;
	border: 1px solid var(--border-color);
	border-radius: 8px;
	background: var(--subtle-fg);
	cursor: grab;
	font-size: 12px;
	font-weight: 600;
}
.canvas {
	min-height: 560px;
}
.hint {
	margin-top: 18px;
	color: var(--text-muted);
	font-size: 11px;
}
.code {
	font-family: var(--font-stack-monospace);
	font-size: 11px;
}
.validation {
	margin-top: 16px;
	padding: 10px;
	border-radius: 8px;
	background: var(--orange-50);
	color: var(--orange-700);
	font-size: 11px;
}
.validation ul {
	padding-left: 18px;
	margin: 6px 0 0;
}
.builder-loading {
	padding: 40px;
	text-align: center;
}
</style>
