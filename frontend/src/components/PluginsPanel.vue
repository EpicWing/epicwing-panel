<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";
import { auth } from "../stores/auth";

interface Row {
  id: string;
  package_id: string;
  registry: string;
  name: string;
  version: string;
  category: string;
  path: string;
  installed_at: string;
  latest_version: string | null;
}

const props = defineProps<{ serverId: string; permissions: string[] }>();

const rows = ref<Row[]>([]);
const loading = ref(true);
const error = ref("");
const notice = ref("");
const busy = ref<string | null>(null);

const canWrite = () => props.permissions.length === 0 || props.permissions.includes("files.write");
const outdated = (row: Row) => !!row.latest_version && row.latest_version !== row.version;

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "The server could not be reached.";
}

function day(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString();
}

async function load(): Promise<void> {
  try {
    rows.value = await api<Row[]>(`/marketplace/servers/${props.serverId}`);
    error.value = "";
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}

async function update(row: Row): Promise<void> {
  busy.value = row.id;
  error.value = "";
  notice.value = "";
  try {
    await api(`/marketplace/servers/${props.serverId}`, {
      method: "POST",
      body: { registry: row.registry, package_id: row.package_id },
    });
    notice.value = `${row.name} was updated to v${row.latest_version}. Restart the server to load it.`;
    await load();
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = null;
  }
}

async function remove(row: Row): Promise<void> {
  if (!window.confirm(`Remove ${row.name}? The file ${row.path} is deleted.`)) return;
  busy.value = row.id;
  error.value = "";
  notice.value = "";
  try {
    await api(`/marketplace/servers/${props.serverId}/${row.id}`, { method: "DELETE" });
    notice.value = `${row.name} was removed. Restart the server to unload it.`;
    await load();
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = null;
  }
}

onMounted(() => void load());
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-end justify-between gap-4">
      <div>
        <h2 class="text-2xl font-semibold">Plugins</h2>
        <p class="mt-2 text-sm text-ink-400">Plugins and mods added from the marketplace.</p>
      </div>
      <RouterLink
        v-if="auth.state.user?.is_admin"
        to="/admin/marketplace"
        class="rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-200 transition hover:border-ink-600 hover:text-ink-100"
      >
        Browse marketplace
      </RouterLink>
    </div>

    <p v-if="error" role="alert" class="rounded-lg border border-bad/30 bg-bad/10 px-4 py-2.5 text-sm text-bad">{{ error }}</p>
    <p v-if="notice" role="status" class="rounded-lg border border-ok/30 bg-ok/10 px-4 py-2.5 text-sm text-ok">{{ notice }}</p>

    <div v-if="loading" class="space-y-3" aria-busy="true">
      <div class="skeleton h-16" />
      <div class="skeleton h-16" />
    </div>

    <div v-else-if="rows.length === 0" class="rounded-xl border border-dashed border-ink-700 px-6 py-14 text-center">
      <p class="text-ink-100">No plugins yet</p>
      <p class="mx-auto mt-1 max-w-md text-sm text-ink-400">
        Add plugins and mods from the marketplace. Files you upload yourself do not show here.
      </p>
    </div>

    <div v-else class="divide-y divide-ink-700 overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
      <article v-for="row in rows" :key="row.id" class="flex flex-wrap items-center gap-4 px-5 py-4">
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-baseline gap-2">
            <h3 class="font-semibold text-ink-100">{{ row.name }}</h3>
            <span class="font-mono text-xs text-ink-400">v{{ row.version }}</span>
            <span
              v-if="outdated(row)"
              class="rounded-md bg-accent-500/15 px-1.5 py-0.5 text-[11px] font-medium text-accent-400"
            >v{{ row.latest_version }} available</span>
          </div>
          <p class="mt-1 truncate font-mono text-xs text-ink-500">
            {{ row.path }}<template v-if="day(row.installed_at)"> · added {{ day(row.installed_at) }}</template>
          </p>
        </div>
        <div v-if="canWrite()" class="flex shrink-0 gap-2">
          <button
            v-if="outdated(row)"
            class="rounded-lg bg-accent-500 px-4 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-40"
            :disabled="busy !== null"
            @click="update(row)"
          >
            {{ busy === row.id ? "Updating…" : "Update" }}
          </button>
          <button
            class="rounded-lg border border-ink-700 px-4 py-1.5 text-sm text-ink-300 transition hover:border-bad/50 hover:text-bad disabled:opacity-40"
            :disabled="busy !== null"
            @click="remove(row)"
          >
            Remove
          </button>
        </div>
      </article>
    </div>
  </div>
</template>
