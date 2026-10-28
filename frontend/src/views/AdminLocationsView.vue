<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

interface Location {
  name: string;
  nodes: number;
  online: number;
  servers: number;
}

const { t } = useI18n();
const rows = ref<Location[]>([]);
const loading = ref(true);
const error = ref("");
let timer: number | undefined;

async function load() {
  try {
    rows.value = await api<Location[]>("/admin/locations");
    error.value = "";
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t("common.unreachable");
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void load();
  timer = window.setInterval(() => void load(), 10000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <AppLayout area="admin" :title="t('locations.title')" :subtitle="t('locations.subtitle')">
    <p v-if="error" role="alert" class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="loading" class="text-sm text-ink-400">…</p>
    <div
      v-else-if="rows.length === 0"
      class="flex min-h-[14rem] items-center justify-center rounded-xl border border-ink-700 bg-ink-900 text-center"
    >
      <div>
        <h3 class="text-lg font-semibold">{{ t("locations.empty") }}</h3>
        <p class="mt-2 text-sm text-ink-400">{{ t("locations.emptyBody") }}</p>
      </div>
    </div>
    <div v-else class="overflow-x-auto rounded-xl border border-ink-700 bg-ink-900">
      <table class="w-full text-left text-sm">
        <thead class="text-xs uppercase tracking-wide text-ink-400">
          <tr>
            <th class="px-4 py-3 font-medium">{{ t("locations.name") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("locations.nodes") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("locations.online") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("locations.servers") }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-ink-800">
          <tr v-for="row in rows" :key="row.name">
            <td class="px-4 py-3 font-medium" :class="row.name ? '' : 'text-ink-400'">
              {{ row.name || t("locations.unassigned") }}
            </td>
            <td class="px-4 py-3 font-mono">{{ row.nodes }}</td>
            <td class="px-4 py-3 font-mono" :class="row.online === row.nodes ? 'text-ok' : 'text-ink-300'">
              {{ row.online }}
            </td>
            <td class="px-4 py-3 font-mono">{{ row.servers }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppLayout>
</template>
