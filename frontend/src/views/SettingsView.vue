<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import TwoFactorPanel from "../components/TwoFactorPanel.vue";

const MIN_LENGTH = 12;

const { t } = useI18n();

const current = ref("");
const next = ref("");
const repeat = ref("");
const error = ref("");
const done = ref(false);
const busy = ref(false);

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";

async function submit() {
  error.value = "";
  done.value = false;

  if (next.value.length < MIN_LENGTH) {
    error.value = t("settings.tooShort", { min: MIN_LENGTH });
    return;
  }
  if (next.value !== repeat.value) {
    error.value = t("settings.mismatch");
    return;
  }

  busy.value = true;
  try {
    await api<void>("/auth/password", {
      method: "POST",
      body: { current_password: current.value, new_password: next.value },
    });
    current.value = "";
    next.value = "";
    repeat.value = "";
    done.value = true;
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t("common.unreachable");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <AppLayout :title="t('settings.title')" :subtitle="t('settings.subtitle')">
    <section class="max-w-lg rounded-xl border border-ink-700 bg-ink-900 p-6">
      <h2 class="text-lg font-semibold">{{ t("settings.passwordTitle") }}</h2>
      <p class="mt-1 text-sm text-ink-400">{{ t("settings.passwordBody", { min: MIN_LENGTH }) }}</p>

      <form class="mt-5 space-y-4" @submit.prevent="submit">
        <div>
          <label for="current" class="mb-1.5 block text-sm text-ink-300">
            {{ t("settings.currentPassword") }}
          </label>
          <input
            id="current"
            v-model="current"
            type="password"
            autocomplete="current-password"
            required
            :class="inputClass"
          />
        </div>
        <div>
          <label for="new" class="mb-1.5 block text-sm text-ink-300">
            {{ t("settings.newPassword") }}
          </label>
          <input
            id="new"
            v-model="next"
            type="password"
            autocomplete="new-password"
            required
            :class="inputClass"
          />
        </div>
        <div>
          <label for="repeat" class="mb-1.5 block text-sm text-ink-300">
            {{ t("settings.repeatPassword") }}
          </label>
          <input
            id="repeat"
            v-model="repeat"
            type="password"
            autocomplete="new-password"
            required
            :class="inputClass"
          />
        </div>

        <p
          v-if="error"
          role="alert"
          class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
        >
          {{ error }}
        </p>
        <p
          v-if="done"
          role="status"
          class="rounded-md border border-ok/40 bg-ok/10 px-3 py-2 text-sm text-ok"
        >
          {{ t("settings.success") }}
        </p>

        <button
          type="submit"
          :disabled="busy"
          class="rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60"
        >
          {{ busy ? t("settings.submitting") : t("settings.submit") }}
        </button>
      </form>
    </section>
    <TwoFactorPanel class="mt-6" />
  </AppLayout>
</template>
