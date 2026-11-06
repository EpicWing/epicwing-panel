<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

import { type ThemeChoice, useTheme } from "../composables/useTheme";

const { locale } = useI18n();
const { choice, setTheme } = useTheme();

// Texte lokal gehalten, damit keine Sprachdateien angefasst werden müssen
const de = computed(() => String(locale.value).startsWith("de"));
const title = computed(() => (de.value ? "Darstellung" : "Appearance"));
const hint = computed(() =>
  de.value
    ? "System folgt der Einstellung deines Geräts."
    : "System follows the setting of your device.",
);
const options = computed<{ value: ThemeChoice; label: string }[]>(() => [
  { value: "light", label: de.value ? "Hell" : "Light" },
  { value: "dark", label: de.value ? "Dunkel" : "Dark" },
  { value: "system", label: "System" },
]);
</script>

<template>
  <section class="rounded-xl border border-ink-700 bg-ink-900 p-6">
    <h2 class="text-base font-semibold">{{ title }}</h2>
    <p class="mt-1 text-sm text-ink-400">{{ hint }}</p>
    <div class="mt-4 grid grid-cols-3 gap-2" role="radiogroup" :aria-label="title">
      <button
        v-for="o in options"
        :key="o.value"
        type="button"
        role="radio"
        :aria-checked="choice === o.value"
        class="rounded-md border px-3 py-2 text-sm"
        :class="
          choice === o.value
            ? 'border-accent-500 bg-accent-500/15 text-ink-100'
            : 'border-ink-700 text-ink-300 hover:border-ink-600'
        "
        @click="setTheme(o.value)"
      >
        {{ o.label }}
      </button>
    </div>
  </section>
</template>
