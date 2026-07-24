<script setup>
	import FeatureWorkspace from '@/components/workspace/FeatureWorkspace.vue'
	import { aiQueueDefinition } from '@/features/workspaces/definitions'
</script>

<template>
	<FeatureWorkspace :definition="aiQueueDefinition" />
</template>
