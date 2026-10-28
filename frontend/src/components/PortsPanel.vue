<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";

interface Row {
  id: string;
  ip: string;
  port: number;
  is_primary: boolean;
}

const props = defineProps<{ serverId: string; permissions: string[] }>();
const emit = defineEmits<{ changed: [rows: Row[]] }>();

const rows = ref<Row[]>([]);
const free = ref<Row[]>([]);
const loading = ref(true);
const busy = ref(false);
const error = ref("");
const picking = ref(false);
const selected = ref("");

const canView = computed(() => props.permissions.includes("allocations.view"));
const canManage = computed(() => props.permissions.includes("allocations.manage"));
const base = computed(() => `/servers/${props.serverId}/allocations`);

const buttonClass =
  "rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const ghostClass =
  "rounded-lg border border-ink-700 px-3 py-1.5 text-xs text-ink-200 transition hover:border-accent-500 disabled:opacity-40";
const dangerClass =
  "rounded-lg border border-bad/50 px-3 py-1.5 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-40";

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "The panel is not reachable.";
}

function setRows(next: Row[]): void {
  rows.value = next;
  emit("changed", next);
}

async function load(): Promise<void> {
  if (!canView.value) {
    loading.value = false;
    return;
  }
  try {
    setRows(await api<Row[]>(base.value));
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}

// Führt eine Änderung aus, sperrt die Buttons dabei und zeigt Fehler im Panel an.
async function run(action: () => Promise<void>): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    await action();
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

async function openPicker(): Promise<void> {
  await run(async () => {
    const list = await api<Row[]>(`${base.value}/free`);
    free.value = list;
    selected.value = list[0]?.id ?? "";
    picking.value = true;
  });
}

async function add(): Promise<void> {
  if (!selected.value) return;
  await run(async () => {
    setRows(await api<Row[]>(base.value, { method: "POST", body: { allocation_id: selected.value } }));
    picking.value = false;
  });
}

async function makePrimary(row: Row): Promise<void> {
  await run(async () => {
    setRows(await api<Row[]>(`${base.value}/${row.id}/primary`, { method: "PUT" }));
  });
}

async function remove(row: Row): Promise<void> {
  if (!window.confirm(`Remove ${row.ip}:${row.port}? The container is recreated.`)) return;
  await run(async () => {
    await api<void>(`${base.value}/${row.id}`, { method: "DELETE" });
    setRows(await api<Row[]>(base.value));
  });
}

onMounted(load);
</script>

<template>
  <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
    <div class="flex items-center justify-between">
      <h3 class="text-lg font-semibold">Port Allocations</h3>
      <button v-if="canManage && !picking" :class="buttonClass" :disabled="busy" @click="openPicker">
        New Allocation
      </button>
    </div>

    <p v-if="error" class="mt-4 rounded-lg border border-bad/50 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>

    <p v-if="!canView" class="mt-5 text-sm text-ink-400">
      You do not have permission to view the ports of this server.
    </p>
    <template v-else>
      <div v-if="picking" class="mt-5 rounded-lg border border-ink-700 bg-ink-950 p-4">
        <p v-if="free.length === 0" class="text-sm text-ink-400">
          There are no free allocations on this node. An admin has to add more ports to the node first.
        </p>
        <div v-else class="flex flex-wrap items-center gap-3">
          <select
            v-model="selected"
            class="rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-sm outline-none focus:border-accent-500"
          >
            <option v-for="row in free" :key="row.id" :value="row.id">{{ row.ip }}:{{ row.port }}</option>
          </select>
          <button :class="buttonClass" :disabled="busy || !selected" @click="add">
            {{ busy ? "Adding…" : "Add" }}
          </button>
          <button :class="ghostClass" :disabled="busy" @click="picking = false">Cancel</button>
        </div>
      </div>

      <p v-if="loading" class="mt-5 text-sm text-ink-400">Loading…</p>
      <div v-else class="mt-5 space-y-2">
        <div
          v-for="row in rows"
          :key="row.id"
          class="flex items-center justify-between rounded-lg border border-ink-700 bg-ink-950 p-4"
        >
          <p class="font-mono text-sm text-ink-200">
            ◉ &nbsp; {{ row.ip }}:{{ row.port }}
            <span v-if="row.is_primary" class="ml-2 rounded bg-accent-500/15 px-2 py-1 text-xs text-accent-300">
              Primary
            </span>
          </p>
          <div v-if="canManage && !row.is_primary" class="flex gap-2">
            <button :class="ghostClass" :disabled="busy" @click="makePrimary(row)">Make primary</button>
            <button :class="dangerClass" :disabled="busy" @click="remove(row)">Remove</button>
          </div>
        </div>
        <p v-if="rows.length === 0" class="text-sm text-ink-400">This server has no allocations.</p>
      </div>
      <p v-if="canManage" class="mt-4 text-xs text-ink-400">
        Changes recreate the container. Stop the server first, running servers are refused.
      </p>
    </template>
  </div>
</template>
