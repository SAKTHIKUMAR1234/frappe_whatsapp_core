<script setup>
	import FeatureWorkspace from '@/components/workspace/FeatureWorkspace.vue'
	import { healthDefinition } from '@/features/workspaces/definitions'
</script>

<template>
	<FeatureWorkspace :definition="healthDefinition" />
</template>
