<script setup lang="ts">
defineProps<{ title: string; text: string }>();
</script>

<template>
  <div class="flex flex-col items-center rounded-xl border border-ink-700 bg-ink-900 px-6 py-14 text-center">
    <div class="flex h-14 w-14 items-center justify-center rounded-full bg-ink-800 text-ink-300">
      <svg viewBox="0 0 24 24" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m21 2-9.6 9.6" />
        <circle cx="7.5" cy="15.5" r="5.5" />
        <path d="m15.5 7.5 3 3L22 7l-3-3" />
      </svg>
    </div>
    <p class="mt-4 text-lg font-medium">{{ title }}</p>
    <p class="mt-1 max-w-sm text-sm text-ink-400">{{ text }}</p>
  </div>
</template>
