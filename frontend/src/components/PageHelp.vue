<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import type { GuideSection } from "../lib/adminGuide";
import { userGuide } from "../lib/userGuide";
import Modal from "./Modal.vue";

// A link that opens short help for this page in a popup. With "remember" set, the popup
// also opens by itself the first time someone visits the page in this browser.
const props = defineProps<{ title: string; topics: string[]; label?: string; remember?: string }>();

const open = ref(false);
const copied = ref("");

const sections = computed<GuideSection[]>(() => {
  const all = userGuide.flatMap((group) => group.sections);
  return props.topics
    .map((id) => all.find((section) => section.id === id))
    .filter((section): section is GuideSection => !!section);
});

function storageKey(): string {
  return `epicwing.help.${props.remember}`;
}

onMounted(() => {
  if (!props.remember) return;
  try {
    if (!localStorage.getItem(storageKey())) open.value = true;
  } catch {
    // No storage (private mode): just do not open by itself.
  }
});

function close(): void {
  open.value = false;
  if (!props.remember) return;
  try {
    localStorage.setItem(storageKey(), "1");
  } catch {
    // Nothing to do, it may open again next time.
  }
}

async function copy(id: string, text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = id;
    setTimeout(() => {
      if (copied.value === id) copied.value = "";
    }, 2000);
  } catch {
    copied.value = "";
  }
}
</script>

<template>
  <button type="button" class="underline hover:text-ink-100" @click="open = true">{{ label ?? "How does this work?" }}</button>

  <Modal :model-value="open" :title="title" @update:model-value="(value) => (value ? (open = true) : close())">
    <div class="-mr-2 max-h-[65vh] space-y-6 overflow-y-auto pr-2 text-left">
      <section v-for="section in sections" :key="section.id">
        <h3 class="text-base font-semibold text-ink-100">{{ section.title }}</h3>
        <p class="mt-2 text-sm leading-relaxed text-ink-300">{{ section.summary }}</p>
        <ol v-if="section.steps?.length" class="mt-3 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-ink-300">
          <li v-for="step in section.steps" :key="step">{{ step }}</li>
        </ol>
        <div v-if="section.code" class="relative mt-3">
          <pre class="overflow-x-auto rounded-md border border-ink-700 bg-ink-800 p-3 pr-20 font-mono text-xs text-ink-300">{{ section.code }}</pre>
          <button
            type="button"
            class="absolute right-2 top-2 rounded-md border border-ink-700 bg-ink-900 px-2 py-1 text-xs text-ink-300 hover:bg-ink-800"
            @click="copy(section.id, section.code ?? '')"
          >
            {{ copied === section.id ? "Copied" : "Copy" }}
          </button>
        </div>
        <p v-for="tip in section.tips ?? []" :key="tip" class="mt-3 text-sm text-ink-400">{{ tip }}</p>
        <p v-for="warning in section.warnings ?? []" :key="warning" class="mt-3 rounded-md border border-warn/40 px-3 py-2 text-sm text-warn">
          {{ warning }}
        </p>
      </section>
    </div>
    <template #footer>
      <button type="button" class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 hover:bg-accent-400" @click="close">
        Got it
      </button>
    </template>
  </Modal>
</template>
