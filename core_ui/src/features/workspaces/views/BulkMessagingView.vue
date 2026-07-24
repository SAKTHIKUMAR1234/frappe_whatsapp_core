<script setup>
	import FeatureWorkspace from '@/components/workspace/FeatureWorkspace.vue'
	import { bulkMessagingDefinition } from '@/features/workspaces/definitions'
</script>

<template>
	<FeatureWorkspace :definition="bulkMessagingDefinition" />
</template>
