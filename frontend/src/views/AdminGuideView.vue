<script setup lang="ts">
import { computed, ref } from "vue";

import AppLayout from "../components/AppLayout.vue";
import { guide } from "../lib/adminGuide";

const query = ref("");

const groups = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) {
    return guide;
  }
  return guide
    .map((group) => ({
      ...group,
      sections: group.sections.filter((s) =>
        [s.title, s.summary, s.code ?? "", ...(s.steps ?? []), ...(s.tips ?? [])].join(" ").toLowerCase().includes(q),
      ),
    }))
    .filter((group) => group.sections.length > 0);
});

function jump(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
</script>

<template>
  <AppLayout area="admin" title="Guide" subtitle="How each part of EpicWing works.">
    <div class="grid gap-8 lg:grid-cols-[14rem_minmax(0,1fr)]">
      <nav class="hidden lg:block" aria-label="Guide sections">
        <div class="sticky top-4 space-y-5 text-sm">
          <div v-for="group in groups" :key="group.id">
            <p class="mb-1.5 text-xs font-medium uppercase tracking-wide text-ink-400">{{ group.title }}</p>
            <ul class="space-y-1">
              <li v-for="section in group.sections" :key="section.id">
                <button type="button" class="text-left text-ink-300 hover:underline" @click="jump(section.id)">
                  {{ section.title }}
                </button>
              </li>
            </ul>
          </div>
        </div>
      </nav>

      <div class="min-w-0 space-y-10">
        <input
          v-model="query"
          type="search"
          placeholder="Search the guide"
          aria-label="Search the guide"
          class="w-full rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm"
        />
        <p v-if="groups.length === 0" class="text-sm text-ink-400">Nothing found.</p>

        <section v-for="group in groups" :key="group.id" class="space-y-4">
          <h2 class="text-lg font-semibold">{{ group.title }}</h2>
          <article
            v-for="section in group.sections"
            :id="section.id"
            :key="section.id"
            class="scroll-mt-4 rounded-xl border border-ink-700 bg-ink-900 p-5"
          >
            <h3 class="font-semibold">{{ section.title }}</h3>
            <p class="mt-2 text-sm text-ink-300">{{ section.summary }}</p>
            <ol v-if="section.steps?.length" class="mt-3 list-decimal space-y-1 pl-5 text-sm text-ink-300">
              <li v-for="step in section.steps" :key="step">{{ step }}</li>
            </ol>
            <pre v-if="section.code" class="mt-3 overflow-x-auto rounded-md border border-ink-700 bg-ink-800 p-3 font-mono text-xs text-ink-300">{{ section.code }}</pre>
            <ul v-if="section.tips?.length" class="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-400">
              <li v-for="tip in section.tips" :key="tip">{{ tip }}</li>
            </ul>
          </article>
        </section>
      </div>
    </div>
  </AppLayout>
</template>
