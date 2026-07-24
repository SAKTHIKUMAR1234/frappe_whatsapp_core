<script setup>
	import FeatureWorkspace from '@/components/workspace/FeatureWorkspace.vue'
	import { connectorsDefinition } from '@/features/workspaces/definitions'
</script>

<template>
	<FeatureWorkspace :definition="connectorsDefinition" />
</template>
