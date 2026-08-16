<script setup>
	import { computed } from 'vue'
	import { useRoute } from 'vue-router'
	import AutomationFlowListView from '@/features/flows/views/AutomationFlowListView.vue'
	import FlowListView from '@/features/flows/views/FlowListView.vue'

	const route = useRoute()
	const selectedType = computed(() =>
		route.query.flow_type === 'automation' ? 'automation' : 'meta',
	)
</script>

<template>
	<!--
		One Flow workspace owns type selection and creation. Meta Forms are still
		stored by Meta/Integration, while custom automation graphs remain Core
		records; the UI boundary does not blur those production ownership rules.
	-->
	<AutomationFlowListView v-if="selectedType === 'automation'" />
	<FlowListView v-else />
</template>
