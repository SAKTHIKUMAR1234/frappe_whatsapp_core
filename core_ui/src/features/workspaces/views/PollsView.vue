<script setup>
	import FeatureWorkspace from '@/components/workspace/FeatureWorkspace.vue'
	import { pollsDefinition } from '@/features/workspaces/definitions'
</script>

<template>
	<FeatureWorkspace :definition="pollsDefinition" />
</template>
