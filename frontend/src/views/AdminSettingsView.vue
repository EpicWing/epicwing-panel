<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import { applyPanelName } from "../lib/panel";

interface Settings {
  name: string;
  discord_url: string;
  docs_url: string;
  github_url: string;
  support_url: string;
}

const { t } = useI18n();
const form = ref<Settings>({ name: "", discord_url: "", docs_url: "", github_url: "", support_url: "" });
const loading = ref(true);
const busy = ref(false);
const error = ref("");
const saved = ref(false);


const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

async function load() {
  try {
    form.value = await api<Settings>("/admin/settings");
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}

async function save() {
  error.value = "";
  saved.value = false;
  busy.value = true;
  try {
    const data = await api<Settings>("/admin/settings", { method: "PUT", body: form.value });
    form.value = data;
    applyPanelName(data.name);
    saved.value = true;
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <AppLayout area="admin" :title="t('panel.title')" :subtitle="t('panel.subtitle')">
    <p v-if="error" role="alert" class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="loading" class="text-sm text-ink-400">…</p>
    <form v-else class="max-w-2xl space-y-6" @submit.prevent="save">
      <section class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <h2 class="text-lg font-semibold">{{ t("panel.generalTitle") }}</h2>
        <div class="mt-4">
          <label for="panel-name" class="mb-1.5 block text-sm text-ink-300">{{ t("panel.name") }}</label>
          <input id="panel-name" v-model="form.name" required maxlength="40" :class="inputClass" />
          <p class="mt-1.5 text-xs text-ink-400">{{ t("panel.nameHint") }}</p>
        </div>
      </section>


      <div class="flex items-center gap-4">
        <button
          type="submit"
          class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60"
          :disabled="busy"
        >
          {{ busy ? t("panel.saving") : t("panel.save") }}
        </button>
        <p v-if="saved" role="status" class="text-sm text-ok">{{ t("panel.saved") }}</p>
      </div>
    </form>
  </AppLayout>
</template>
