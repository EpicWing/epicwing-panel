<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";

const props = defineProps<{ value: number | null | undefined }>();
const shown = ref(props.value ?? 0);
let frame = 0;

// Counts from the current to the new value in 600 ms, no animation if reduced motion is on.
watch(
  () => props.value,
  (to) => {
    cancelAnimationFrame(frame);
    if (to === null || to === undefined) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      shown.value = to;
      return;
    }
    const from = shown.value;
    const start = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / 600);
      shown.value = Math.round(from + (to - from) * (1 - Math.pow(1 - progress, 3)));
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
  },
  { immediate: true },
);

onBeforeUnmount(() => cancelAnimationFrame(frame));
</script>

<template>
  <span>{{ value === null || value === undefined ? "–" : shown }}</span>
</template>
