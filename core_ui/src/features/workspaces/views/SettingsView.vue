<script setup>
	import FeatureWorkspace from '@/components/workspace/FeatureWorkspace.vue'
	import { settingsDefinition } from '@/features/workspaces/definitions'
</script>

<template>
	<FeatureWorkspace :definition="settingsDefinition" />
</template>
