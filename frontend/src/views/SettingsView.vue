<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import AppLayout from "../components/AppLayout.vue";
import { type UiMode, ui } from "../stores/ui";

const { t } = useI18n();

const modes = computed<{ id: UiMode; title: string; body: string }[]>(() => [
  { id: "simple", title: t("settings.modeSimple"), body: t("settings.modeSimpleBody") },
  { id: "advanced", title: t("settings.modeAdvanced"), body: t("settings.modeAdvancedBody") },
]);
</script>

<template>
  <AppLayout :title="t('settings.title')" :subtitle="t('settings.subtitle')">
    <section class="rounded-xl border border-ink-700 bg-ink-900 p-6">
      <h2 class="text-lg font-semibold">{{ t("settings.interfaceTitle") }}</h2>
      <p class="mt-1 text-sm text-ink-400">{{ t("settings.interfaceBody") }}</p>

      <div role="radiogroup" class="mt-5 grid gap-4 md:grid-cols-2">
        <button
          v-for="mode in modes"
          :key="mode.id"
          type="button"
          role="radio"
          :aria-checked="ui.state.mode === mode.id"
          class="rounded-lg border p-4 text-left transition"
          :class="
            ui.state.mode === mode.id
              ? 'border-accent-500 bg-accent-500/5'
              : 'border-ink-700 hover:border-ink-600'
          "
          @click="ui.setMode(mode.id)"
        >
          <span class="flex items-center gap-2.5">
            <span
              class="flex h-4 w-4 items-center justify-center rounded-full border"
              :class="ui.state.mode === mode.id ? 'border-accent-500' : 'border-ink-600'"
            >
              <span
                v-if="ui.state.mode === mode.id"
                class="h-2 w-2 rounded-full bg-accent-500"
              ></span>
            </span>
            <span class="font-medium">{{ mode.title }}</span>
          </span>
          <span class="mt-2 block text-sm text-ink-400">{{ mode.body }}</span>
        </button>
      </div>

      <p class="mt-4 text-xs text-ink-400">{{ t("settings.storedLocal") }}</p>
    </section>
  </AppLayout>
</template>
