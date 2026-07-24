<script setup>
	import FeatureWorkspace from '@/components/workspace/FeatureWorkspace.vue'
	import { templateCatalogDefinition } from '@/features/workspaces/definitions'
</script>

<template>
	<FeatureWorkspace :definition="templateCatalogDefinition" />
</template>
