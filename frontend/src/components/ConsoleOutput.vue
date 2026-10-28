<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";

import { type ConsoleLine, segmentClass } from "../utils/ansi";

const props = defineProps<{
  lines: ConsoleLine[];
  placeholder: string;
  offlineText?: string;
}>();

const scroller = ref<HTMLElement | null>(null);
let pinned = true;

const empty = computed(() => props.lines.length === 1 && props.lines[0].segments.length === 0);

function toBottom(): void {
  const el = scroller.value;
  if (el) el.scrollTop = el.scrollHeight;
}

// Follow the output only while the reader is at the bottom.
function onScroll(): void {
  const el = scroller.value;
  if (el) pinned = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
}

watch(
  () => props.lines,
  async () => {
    if (!pinned) return;
    await nextTick();
    toBottom();
  },
);

onMounted(toBottom);
</script>

<template>
  <div
    ref="scroller"
    class="overflow-auto bg-[#090a0c] p-4 font-mono text-xs leading-5 text-ink-200"
    role="log"
    @scroll.passive="onScroll"
  >
    <p v-if="offlineText" class="text-ink-400">{{ offlineText }}</p>
    <p v-else-if="empty" class="text-ink-400">{{ placeholder }}</p>
    <template v-else>
      <div v-for="line in lines" :key="line.id" v-memo="[line.rev]" class="min-h-5 whitespace-pre-wrap break-words">
        <span v-for="(segment, index) in line.segments" :key="index" :class="segmentClass(segment)">{{ segment.text }}</span>
      </div>
    </template>
  </div>
</template>
