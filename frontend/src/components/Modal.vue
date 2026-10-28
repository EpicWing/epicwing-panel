<script setup lang="ts">
import { onBeforeUnmount, watch } from "vue";

const props = withDefaults(
  defineProps<{ modelValue: boolean; title: string; dismissable?: boolean }>(),
  { dismissable: true },
);
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();

function close(): void {
  emit("update:modelValue", false);
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape" && props.dismissable) close();
}

function onBackdrop(): void {
  if (props.dismissable) close();
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) document.addEventListener("keydown", onKey);
    else document.removeEventListener("keydown", onKey);
  },
  { immediate: true },
);

onBeforeUnmount(() => document.removeEventListener("keydown", onKey));
</script>

<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      @mousedown.self="onBackdrop"
    >
      <div
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        class="w-full max-w-lg rounded-xl border border-ink-700 bg-ink-900 p-6 shadow-2xl"
      >
        <div class="mb-4 flex items-start justify-between gap-4">
          <h2 class="text-xl font-semibold">{{ title }}</h2>
          <button
            type="button"
            aria-label="Close"
            class="rounded-md p-1 text-ink-400 transition hover:text-ink-100"
            @click="close"
          >
            <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
        <slot />
        <div v-if="$slots.footer" class="mt-6 flex justify-end gap-2">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </Teleport>
</template>
