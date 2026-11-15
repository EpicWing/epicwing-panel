<script setup lang="ts">
defineProps<{ value: number | null | undefined }>();
</script>

<template>
  <span class="tabular-nums">{{ value === null || value === undefined ? "–" : value }}</span>
</template>
