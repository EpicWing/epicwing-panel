<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { avatarState } from "../lib/avatar";

const props = withDefaults(defineProps<{ userId?: string | null; label: string; size?: number }>(), {
  userId: null,
  size: 32,
});

const failed = ref(false);
watch(
  () => [props.userId, avatarState.version],
  () => {
    failed.value = false;
  },
);

const src = computed(() => (props.userId ? `/api/avatars/${props.userId}?v=${avatarState.version}` : ""));
const initial = computed(() => (props.label.trim().charAt(0) || "?").toUpperCase());
const box = computed(() => ({ width: `${props.size}px`, height: `${props.size}px` }));
const fontSize = computed(() => `${Math.round(props.size * 0.4)}px`);
</script>

<template>
  <img
    v-if="src && !failed"
    :src="src"
    :alt="label"
    class="shrink-0 rounded-full object-cover"
    :style="box"
    @error="failed = true"
  />
  <div
    v-else
    class="flex shrink-0 items-center justify-center rounded-full bg-ink-700 font-semibold text-ink-100"
    :style="{ ...box, fontSize }"
    aria-hidden="true"
  >
    {{ initial }}
  </div>
</template>
