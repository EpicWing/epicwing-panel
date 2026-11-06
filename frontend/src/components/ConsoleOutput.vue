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

// "Prefix: message" is shown with a coloured prefix, like a container prompt.
const offlineParts = computed(() => {
  const text = props.offlineText ?? "";
  const index = text.indexOf(": ");
  return index < 0 ? ["", text] : [text.slice(0, index + 1), text.slice(index + 2)];
});

// Lines written by the panel itself, e.g. "[EpicWing] Preparing installation ...".
function isPanelLine(line: ConsoleLine): boolean {
  return line.segments[0]?.text.startsWith("[EpicWing]") ?? false;
}

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
    class="overflow-auto console-surface bg-ink-950 p-4 font-mono text-xs leading-5 text-ink-200"
    role="log"
    @scroll.passive="onScroll"
  >
    <p v-if="offlineText" class="text-ink-200"><span class="font-semibold text-accent-400">{{ offlineParts[0] }}</span> {{ offlineParts[1] }}</p>
    <p v-else-if="empty" class="text-ink-400">{{ placeholder }}</p>
    <template v-else>
      <div v-for="line in lines" :key="line.id" v-memo="[line.rev]" :class="['min-h-5 whitespace-pre-wrap break-words', isPanelLine(line) ? 'text-accent-400' : '']">
        <span v-for="(segment, index) in line.segments" :key="index" :class="segmentClass(segment)">{{ segment.text }}</span>
      </div>
    </template>
  </div>
</template>
