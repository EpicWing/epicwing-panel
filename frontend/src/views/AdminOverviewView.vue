<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

const { t } = useI18n();
const nodeCount = ref<number | null>(null);

const steps = computed(() => [
  {
    title: t("admin.step1Title"),
    body: t("admin.step1Body"),
    done: (nodeCount.value ?? 0) > 0,
    to: "/admin/nodes",
  },
  { title: t("admin.step2Title"), body: t("admin.step2Body"), done: false, to: null },
  { title: t("admin.step3Title"), body: t("admin.step3Body"), done: false, to: null },
]);

// The checklist disappears on its own once every step is done.
const allDone = computed(() => steps.value.every((step) => step.done));

onMounted(async () => {
  try {
    nodeCount.value = (await api<unknown[]>("/nodes")).length;
  } catch {
    // Without permission or on an error the number stays empty.
  }
});
</script>

<template>
  <AppLayout area="admin" :title="t('admin.title')" :subtitle="t('admin.subtitle')">
    <div class="grid gap-4 sm:grid-cols-3">
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="text-sm text-ink-400">{{ t("admin.nodes") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold">{{ nodeCount ?? "–" }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="text-sm text-ink-400">{{ t("admin.servers") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold text-ink-600">–</p>
        <p class="mt-1 text-xs text-ink-400">{{ t("admin.notImplemented") }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="text-sm text-ink-400">{{ t("admin.users") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold text-ink-600">–</p>
        <p class="mt-1 text-xs text-ink-400">{{ t("admin.notImplemented") }}</p>
      </div>
    </div>

    <section v-if="!allDone" class="mt-8">
      <h2 class="mb-4 text-lg font-semibold">{{ t("admin.startTitle") }}</h2>
      <ol class="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
        <li v-for="(step, index) in steps" :key="step.title" class="flex items-center gap-4 p-5">
          <span
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold"
            :class="
              step.done ? 'border-ok/50 bg-ok/10 text-ok' : 'border-ink-600 text-ink-400'
            "
          >
            {{ step.done ? "✓" : index + 1 }}
          </span>
          <div class="min-w-0 flex-1">
            <p class="font-medium">{{ step.title }}</p>
            <p class="text-sm text-ink-400">{{ step.body }}</p>
          </div>
          <span v-if="step.done" class="text-xs text-ok">{{ t("admin.stepDone") }}</span>
          <RouterLink
            v-else-if="step.to"
            :to="step.to"
            class="rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100"
          >
            {{ t("admin.stepOpen") }}
          </RouterLink>
          <span v-else class="text-xs text-ink-400">{{ t("admin.stepSoon") }}</span>
        </li>
      </ol>
    </section>
  </AppLayout>
</template>
