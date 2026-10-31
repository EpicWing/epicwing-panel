<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";

interface AllocationItem {
  id: string;
  ip: string;
  port: number;
  server_id: string | null;
  server_name: string | null;
  is_primary: boolean;
}

// rangeStart and rangeEnd are not needed anymore, every port is allowed.
const props = defineProps<{ nodeId: string; rangeStart?: number; rangeEnd?: number }>();

const { t } = useI18n();

const rows = ref<AllocationItem[]>([]);
const loading = ref(true);
const error = ref("");
const busy = ref(false);
const form = ref<{ ip: string; portStart: number | ""; portEnd: number | "" }>({
  ip: "",
  portStart: "",
  portEnd: "",
});

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const primaryClass =
  "rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const dangerClass =
  "rounded-md border border-bad/50 px-3 py-1.5 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-40";

const freeCount = computed(() => rows.value.filter((r) => r.server_id === null).length);

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

async function load() {
  try {
    rows.value = await api<AllocationItem[]>(`/nodes/${props.nodeId}/allocations`);
    if (!form.value.ip) {
      form.value.ip = rows.value[0]?.ip ?? "";
    }
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}

async function add() {
  error.value = "";
  if (form.value.portStart === "") {
    return;
  }
  const body: Record<string, unknown> = {
    ip: form.value.ip.trim(),
    port_start: Number(form.value.portStart),
  };
  if (form.value.portEnd !== "") {
    body.port_end = Number(form.value.portEnd);
  }
  busy.value = true;
  try {
    await api<AllocationItem[]>(`/nodes/${props.nodeId}/allocations`, { method: "POST", body });
    form.value.portStart = "";
    form.value.portEnd = "";
    await load();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function remove(row: AllocationItem) {
  if (!window.confirm(t("allocations.deleteConfirm", { port: row.port }))) {
    return;
  }
  error.value = "";
  try {
    await api<void>(`/allocations/${row.id}`, { method: "DELETE" });
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

onMounted(() => void load());
</script>

<template>
  <section class="space-y-6">
    <p
      v-if="error"
      role="alert"
      class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
    >
      {{ error }}
    </p>

    <form
      class="grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5 sm:grid-cols-3"
      @submit.prevent="add"
    >
      <p class="text-sm text-ink-300 sm:col-span-3">
        {{ t("allocations.body") }}
      </p>
      <div>
        <label for="a-ip" class="mb-1.5 block text-sm text-ink-300">{{ t("allocations.ip") }}</label>
        <input id="a-ip" v-model="form.ip" required placeholder="203.0.113.10" :class="inputClass" />
        <p class="mt-1.5 text-xs text-ink-400">{{ t("allocations.ipHint") }}</p>
      </div>
      <div>
        <label for="a-start" class="mb-1.5 block text-sm text-ink-300">
          {{ t("allocations.portStart") }}
        </label>
        <input
          id="a-start"
          v-model.number="form.portStart"
          required
          type="number"
          min="1024"
          max="65535"
          :class="inputClass"
        />
      </div>
      <div>
        <label for="a-end" class="mb-1.5 block text-sm text-ink-300">
          {{ t("allocations.portEnd") }}
        </label>
        <input
          id="a-end"
          v-model.number="form.portEnd"
          type="number"
          min="1024"
          max="65535"
          :class="inputClass"
        />
        <p class="mt-1.5 text-xs text-ink-400">{{ t("allocations.portEndHint") }}</p>
      </div>
      <div class="sm:col-span-3">
        <button type="submit" :disabled="busy" :class="primaryClass">
          {{ busy ? t("allocations.adding") : t("allocations.add") }}
        </button>
      </div>
    </form>

    <p v-if="rows.length > 0" class="text-xs text-ink-400">
      {{ t("allocations.summary", { total: rows.length, free: freeCount }) }}
    </p>

    <div class="overflow-x-auto rounded-lg border border-ink-700">
      <div class="max-h-[28rem] overflow-y-auto">
        <table class="w-full text-left text-sm">
          <thead class="sticky top-0 bg-ink-900 text-xs uppercase tracking-wider text-ink-400">
            <tr>
              <th class="px-4 py-3 font-medium">{{ t("allocations.colIp") }}</th>
              <th class="px-4 py-3 font-medium">{{ t("allocations.colPort") }}</th>
              <th class="px-4 py-3 font-medium">{{ t("allocations.colServer") }}</th>
              <th class="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-ink-700">
            <tr v-if="loading">
              <td colspan="4" class="px-4 py-8 text-center text-ink-400">
                {{ t("allocations.loading") }}
              </td>
            </tr>
            <tr v-else-if="rows.length === 0">
              <td colspan="4" class="px-4 py-8 text-center text-sm text-ink-400">
                {{ t("allocations.empty") }}
              </td>
            </tr>
            <tr v-for="row in rows" :key="row.id" class="hover:bg-ink-900/60">
              <td class="px-4 py-2.5 font-mono text-xs text-ink-300">{{ row.ip }}</td>
              <td class="px-4 py-2.5 font-mono text-xs">{{ row.port }}</td>
              <td class="px-4 py-2.5 text-ink-300">
                <template v-if="row.server_name">
                  {{ row.server_name }}
                  <span
                    v-if="row.is_primary"
                    class="ml-1.5 rounded bg-accent-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-400"
                  >
                    {{ t("allocations.primary") }}
                  </span>
                </template>
                <span v-else class="text-ink-400">{{ t("allocations.free") }}</span>
              </td>
              <td class="px-4 py-2.5 text-right">
                <button
                  :class="dangerClass"
                  :disabled="row.server_id !== null"
                  @click="remove(row)"
                >
                  {{ t("allocations.delete") }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>
