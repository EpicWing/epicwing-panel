<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";

interface Backup {
  id: string;
  name: string;
  status: string;
  size_bytes: number;
  sha256: string | null;
  is_locked: boolean;
  ignored: string;
  error: string | null;
  created_by: string | null;
  created_at: string;
  completed_at: string | null;
}

interface BackupList {
  limit: number;
  items: Backup[];
}

const props = defineProps<{ serverId: string; status: string; permissions: string[] }>();

const rows = ref<Backup[]>([]);
const limit = ref(0);
const loading = ref(true);
const error = ref("");
const busy = ref(false);
const restoring = ref<string | null>(null);
const showForm = ref(false);
const form = ref({ name: "", ignored: "", locked: false });
let timer: number | undefined;
let alive = true;

const can = (right: string) => props.permissions.includes(right);
const base = () => `/servers/${props.serverId}/backups`;
const used = computed(() => rows.value.filter((r) => r.status !== "failed").length);
const canCreate = computed(() => can("backups.create") && limit.value > 0 && used.value < limit.value);

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const primaryClass =
  "rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const ghostClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-accent-500 disabled:opacity-40";
const dangerClass =
  "rounded-md border border-bad/50 px-3 py-1.5 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-40";

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Could not reach the server.";
}

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`;
}

function when(iso: string): string {
  return new Date(iso).toLocaleString();
}

function statusClass(s: string): string {
  if (s === "failed") return "text-bad";
  if (s === "ok") return "text-accent-400";
  return "text-ink-300";
}

function schedule() {
  window.clearTimeout(timer);
  if (alive && rows.value.some((r) => r.status === "running")) {
    timer = window.setTimeout(load, 3000);
  }
}

async function load() {
  try {
    const data = await api<BackupList>(base());
    rows.value = data.items;
    limit.value = data.limit;
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
    schedule();
  }
}

async function create() {
  error.value = "";
  busy.value = true;
  try {
    await api(base(), {
      method: "POST",
      body: {
        name: form.value.name.trim() || null,
        ignored: form.value.ignored,
        is_locked: form.value.locked,
      },
    });
    form.value = { name: "", ignored: "", locked: false };
    showForm.value = false;
    await load();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function toggleLock(b: Backup) {
  error.value = "";
  try {
    await api(`${base()}/${b.id}`, { method: "PATCH", body: { is_locked: !b.is_locked } });
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

async function remove(b: Backup) {
  if (!window.confirm(`Delete backup "${b.name}"? This cannot be undone.`)) return;
  error.value = "";
  try {
    await api(`${base()}/${b.id}`, { method: "DELETE" });
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

async function pollRestore(id: string) {
  if (!alive) return;
  try {
    const data = await api<{ state: string; error: string | null }>(`${base()}/${id}/restore`);
    if (data.state === "running") {
      window.setTimeout(() => pollRestore(id), 3000);
      return;
    }
    if (data.state === "failed") {
      error.value = data.error || "The restore failed.";
    }
  } catch (e) {
    error.value = message(e);
  }
  restoring.value = null;
}

async function restore(b: Backup) {
  if (!window.confirm(`Restore "${b.name}"? The current server files will be replaced.`)) return;
  error.value = "";
  try {
    await api(`${base()}/${b.id}/restore`, { method: "POST" });
    restoring.value = b.id;
    pollRestore(b.id);
  } catch (e) {
    error.value = message(e);
  }
}

onMounted(load);
onBeforeUnmount(() => {
  alive = false;
  window.clearTimeout(timer);
});
</script>

<template>
  <section class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-2xl font-semibold">Backups</h2>
        <p class="mt-2 text-sm text-ink-400">
          Create and manage server backups to protect your data.
          <span v-if="!loading">{{ used }} of {{ limit }} used.</span>
        </p>
      </div>
      <button v-if="can('backups.create')" :class="primaryClass" :disabled="!canCreate" @click="showForm = !showForm">
        New Backup
      </button>
    </div>

    <p v-if="error" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="!loading && limit === 0" class="rounded-lg border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-300">
      Backups are disabled for this server. An administrator can set a backup limit.
    </p>

    <form
      v-if="showForm"
      class="grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5"
      @submit.prevent="create"
    >
      <div>
        <label for="b-name" class="mb-1.5 block text-sm text-ink-300">Name (optional)</label>
        <input id="b-name" v-model="form.name" maxlength="128" :class="inputClass" />
      </div>
      <div>
        <label for="b-ignored" class="mb-1.5 block text-sm text-ink-300">Ignored files (one pattern per line)</label>
        <textarea id="b-ignored" v-model="form.ignored" rows="3" maxlength="4096" :class="inputClass" />
      </div>
      <label class="flex items-center gap-2 text-sm text-ink-300">
        <input v-model="form.locked" type="checkbox" /> Lock this backup
      </label>
      <div class="flex gap-2">
        <button type="submit" :class="primaryClass" :disabled="busy">Create</button>
        <button type="button" :class="ghostClass" @click="showForm = false">Cancel</button>
      </div>
    </form>

    <p v-if="loading" class="text-sm text-ink-400">Loading...</p>
    <div
      v-else-if="rows.length === 0"
      class="flex min-h-[16rem] items-center justify-center rounded-xl border border-ink-700 bg-ink-900 text-center"
    >
      <div>
        <h3 class="text-lg font-semibold">No backups found</h3>
        <p class="mt-2 text-sm text-ink-400">This server does not have any backups yet.</p>
      </div>
    </div>

    <ul v-else class="space-y-3">
      <li v-for="b in rows" :key="b.id" class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate font-medium">
              {{ b.name }}
              <span v-if="b.is_locked" class="ml-2 text-xs text-ink-400">locked</span>
            </p>
            <p class="mt-1 text-xs text-ink-400">
              <span :class="statusClass(b.status)">{{ b.status }}</span>
              <span v-if="b.status === 'ok'"> · {{ size(b.size_bytes) }}</span>
              · {{ when(b.created_at) }}
            </p>
            <p v-if="b.error" class="mt-1 text-xs text-bad">{{ b.error }}</p>
            <p v-if="restoring === b.id" class="mt-1 text-xs text-ink-300">Restoring...</p>
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              v-if="can('backups.restore')"
              :class="ghostClass"
              :disabled="b.status !== 'ok' || props.status !== 'offline' || restoring !== null"
              :title="props.status !== 'offline' ? 'Stop the server first' : ''"
              @click="restore(b)"
            >
              Restore
            </button>
            <button v-if="can('backups.create')" :class="ghostClass" @click="toggleLock(b)">
              {{ b.is_locked ? "Unlock" : "Lock" }}
            </button>
            <button
              v-if="can('backups.delete')"
              :class="dangerClass"
              :disabled="b.is_locked || b.status === 'running'"
              @click="remove(b)"
            >
              Delete
            </button>
          </div>
        </div>
      </li>
    </ul>
  </section>
</template>
