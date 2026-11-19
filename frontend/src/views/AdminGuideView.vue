<script setup lang="ts">
import { computed, ref } from "vue";

import AppLayout from "../components/AppLayout.vue";
import GuideIcon from "../components/GuideIcon.vue";
import { guide } from "../lib/adminGuide";

const query = ref("");
const copiedId = ref("");

const titles = new Map<string, string>();
for (const g of guide) {
  for (const s of g.sections) {
    titles.set(s.id, s.title);
  }
}

const groups = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) {
    return guide;
  }
  return guide
    .map((group) => ({
      ...group,
      sections: group.sections.filter((s) =>
        [s.title, s.summary, s.code ?? "", ...(s.steps ?? []), ...(s.tips ?? []), ...(s.warnings ?? [])]
          .join(" ")
          .toLowerCase()
          .includes(q),
      ),
    }))
    .filter((group) => group.sections.length > 0);
});

function jump(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function copy(id: string, text: string) {
  try {
    await navigator.clipboard.writeText(text);
    copiedId.value = id;
    setTimeout(() => {
      if (copiedId.value === id) {
        copiedId.value = "";
      }
    }, 2000);
  } catch {
    copiedId.value = "";
  }
}
</script>

<template>
  <AppLayout area="admin" title="Guide" subtitle="How each part of EpicWing works.">
    <div class="grid gap-10 lg:grid-cols-[15rem_minmax(0,1fr)]">
      <nav class="hidden lg:block" aria-label="Guide sections">
        <div class="sticky top-4 max-h-[calc(100vh-2rem)] space-y-7 overflow-y-auto pr-2 text-sm">
          <div v-for="group in groups" :key="group.id">
            <p class="mb-2 px-2 text-xs font-medium uppercase tracking-wide text-ink-400">{{ group.title }}</p>
            <ul class="space-y-0.5">
              <li v-for="section in group.sections" :key="section.id">
                <button
                  type="button"
                  class="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-ink-300 hover:bg-ink-800"
                  @click="jump(section.id)"
                >
                  <GuideIcon :name="section.icon" class="h-4 w-4 shrink-0 text-ink-400" />
                  <span>{{ section.title }}</span>
                </button>
              </li>
            </ul>
          </div>
        </div>
      </nav>

      <div class="min-w-0 space-y-12">
        <input
          v-model="query"
          type="search"
          placeholder="Search the guide"
          aria-label="Search the guide"
          class="w-full rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm"
        />
        <p v-if="groups.length === 0" class="text-sm text-ink-400">Nothing found.</p>

        <section v-for="group in groups" :key="group.id" class="space-y-6">
          <h2 class="text-xl font-semibold">{{ group.title }}</h2>
          <article
            v-for="section in group.sections"
            :id="section.id"
            :key="section.id"
            class="scroll-mt-4 rounded-xl border border-ink-700 bg-ink-900 p-6"
          >
            <div class="flex items-center gap-3">
              <GuideIcon :name="section.icon" class="accent h-5 w-5 shrink-0" />
              <h3 class="text-base font-semibold">{{ section.title }}</h3>
            </div>

            <p class="mt-4 text-sm leading-relaxed text-ink-300">{{ section.summary }}</p>

            <ol v-if="section.steps?.length" class="steps mt-5 space-y-3 text-sm leading-relaxed text-ink-300">
              <li v-for="step in section.steps" :key="step">
                <span>{{ step }}</span>
              </li>
            </ol>

            <div v-if="section.code" class="relative mt-5">
              <pre
                class="overflow-x-auto rounded-md border border-ink-700 bg-ink-800 p-3 pr-20 font-mono text-xs text-ink-300"
                >{{ section.code }}</pre
              >
              <button
                type="button"
                class="absolute right-2 top-2 rounded-md border border-ink-700 bg-ink-900 px-2 py-1 text-xs text-ink-300 hover:bg-ink-800"
                @click="copy(section.id, section.code ?? '')"
              >
                {{ copiedId === section.id ? "Copied" : "Copy" }}
              </button>
            </div>

            <div v-for="tip in section.tips ?? []" :key="tip" class="note note-tip mt-4">
              <GuideIcon name="info" class="mt-0.5 h-4 w-4 shrink-0" />
              <p>{{ tip }}</p>
            </div>
            <div v-for="warning in section.warnings ?? []" :key="warning" class="note note-warn mt-4">
              <GuideIcon name="alert" class="mt-0.5 h-4 w-4 shrink-0" />
              <p>{{ warning }}</p>
            </div>

            <button
              v-if="section.next && titles.has(section.next)"
              type="button"
              class="mt-5 flex items-center gap-1.5 text-sm text-ink-300 hover:underline"
              @click="jump(section.next ?? '')"
            >
              <span>Next: {{ titles.get(section.next) }}</span>
              <GuideIcon name="arrow-right" class="h-4 w-4" />
            </button>
          </article>
        </section>
      </div>
    </div>
  </AppLayout>
</template>

<style scoped>
.accent {
  color: #fbbf24;
}
.steps {
  list-style: none;
  padding: 0;
  counter-reset: step;
}
.steps li {
  display: flex;
  gap: 0.75rem;
  counter-increment: step;
}
.steps li::before {
  content: counter(step);
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 9999px;
  background: rgba(245, 158, 11, 0.15);
  color: #fbbf24;
  font-size: 0.75rem;
  font-weight: 600;
}
.note {
  display: flex;
  gap: 0.6rem;
  border: 1px solid;
  border-radius: 0.5rem;
  padding: 0.65rem 0.8rem;
  font-size: 0.875rem;
  line-height: 1.5;
}
.note-tip {
  border-color: rgba(56, 189, 248, 0.3);
  background: rgba(56, 189, 248, 0.07);
  color: #bae6fd;
}
.note-warn {
  border-color: rgba(245, 158, 11, 0.35);
  background: rgba(245, 158, 11, 0.08);
  color: #fde68a;
}

/* Heller Modus: dunklere Schrift auf hellem Grund */
:root[data-theme="light"] .accent {
  color: #b36b00;
}
:root[data-theme="light"] .steps li::before {
  background: rgba(245, 158, 11, 0.18);
  color: #b36b00;
}
:root[data-theme="light"] .note-tip {
  border-color: rgba(2, 132, 199, 0.35);
  background: rgba(56, 189, 248, 0.12);
  color: #075985;
}
:root[data-theme="light"] .note-warn {
  border-color: rgba(217, 119, 6, 0.4);
  background: rgba(245, 158, 11, 0.12);
  color: #92400e;
}
</style>
