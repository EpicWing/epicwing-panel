<script setup lang="ts">
import { panelState } from "../lib/panel";

const year = new Date().getFullYear();
</script>

<template>
  <footer class="shrink-0 px-4 py-4 text-xs text-ink-400 lg:px-8">Copyright &copy; {{ year }} {{ panelState.name }}.</footer>
</template>
