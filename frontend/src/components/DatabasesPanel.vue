<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";

interface Database {
  id: string;
  name: string;
  username: string;
  remote: string;
  host: string;
  port: number;
  password: string;
}

interface Listing {
  limit: number;
  items: Database[];
}

const props = defineProps<{ serverId: string; permissions: string[] }>();

const rows = ref<Database[]>([]);
const limit = ref(0);
const loading = ref(true);
const error = ref("");
const notice = ref("");
const busy = ref(false);
const showForm = ref(false);
const formError = ref("");
const form = ref({ name: "", remote: "" });
const revealed = ref<string[]>([]);

const base = () => `/servers/${props.serverId}/databases`;
const manage = computed(() => props.permissions.includes("databases.manage"));
const full = computed(() => limit.value > 0 && rows.value.length >= limit.value);

const inputClass =
  "mt-1 w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const primaryClass =
  "rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const ghostClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-accent-500 disabled:opacity-40";
const dangerClass =
  "rounded-md border border-bad/50 px-3 py-1.5 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-40";

function message(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong.";
}

const isShown = (id: string) => revealed.value.includes(id);

function toggle(id: string) {
  revealed.value = isShown(id)
    ? revealed.value.filter((entry) => entry !== id)
    : [...revealed.value, id];
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    notice.value = "Copied to clipboard.";
  } catch {
    error.value = "Copying is not available in this browser.";
  }
}

async function load() {
  try {
    const data = await api<Listing>(base());
    rows.value = data.items;
    limit.value = data.limit;
    error.value = "";
  } catch (err) {
    error.value = message(err);
  } finally {
    loading.value = false;
  }
}

function openForm() {
  form.value = { name: "", remote: "" };
  formError.value = "";
  showForm.value = true;
}

async function create() {
  busy.value = true;
  formError.value = "";
  try {
    const row = await api<Database>(base(), {
      method: "POST",
      body: { name: form.value.name.trim(), remote: form.value.remote.trim() },
    });
    rows.value.push(row);
    showForm.value = false;
    error.value = "";
    notice.value = "Database created.";
  } catch (err) {
    formError.value = message(err);
  } finally {
    busy.value = false;
  }
}

async function rotate(row: Database) {
  if (!window.confirm(`Create a new password for ${row.name}? The old one stops working.`)) return;
  busy.value = true;
  try {
    const updated = await api<Database>(`${base()}/${row.id}/rotate`, { method: "POST" });
    rows.value = rows.value.map((entry) => (entry.id === row.id ? updated : entry));
    if (!isShown(row.id)) toggle(row.id);
    error.value = "";
    notice.value = "Password changed.";
  } catch (err) {
    error.value = message(err);
  } finally {
    busy.value = false;
  }
}

async function remove(row: Database) {
  if (!window.confirm(`Delete ${row.name}? All its data is lost.`)) return;
  busy.value = true;
  try {
    await api(`${base()}/${row.id}`, { method: "DELETE" });
    rows.value = rows.value.filter((entry) => entry.id !== row.id);
    error.value = "";
    notice.value = "Database deleted.";
  } catch (err) {
    error.value = message(err);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-2xl font-semibold">Databases</h2>
        <p class="mt-2 text-sm text-ink-400">
          Create and manage MySQL databases for your server and see how to connect to them.
        </p>
      </div>
      <div class="flex shrink-0 items-center gap-4">
        <span class="text-sm text-ink-400">{{ rows.length }} / {{ limit }} databases</span>
        <button v-if="manage" :class="primaryClass" :disabled="full" @click="openForm">
          New Database
        </button>
      </div>
    </div>

    <p v-if="notice" class="rounded-md border border-accent-500/40 bg-accent-500/10 px-3 py-2 text-sm text-accent-400">{{ notice }}</p>
    <p v-if="error" class="rounded-md border border-bad/50 bg-bad/10 px-3 py-2 text-sm text-bad">{{ error }}</p>

    <p v-if="loading" class="text-sm text-ink-400">Loading…</p>

    <div v-else-if="!rows.length" class="flex min-h-[24rem] items-center justify-center rounded-xl border border-ink-700 bg-ink-900 text-center">
      <div>
        <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-ink-800 text-2xl">▣</div>
        <h3 class="text-lg font-semibold">No databases found</h3>
        <p class="mt-2 text-sm text-ink-400">Your server does not have any databases yet.</p>
      </div>
    </div>

    <div v-else class="space-y-3">
      <div v-for="row in rows" :key="row.id" class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <h3 class="break-all text-base font-semibold">{{ row.name }}</h3>
          <div v-if="manage" class="flex gap-2">
            <button :class="ghostClass" :disabled="busy" @click="rotate(row)">Rotate password</button>
            <button :class="dangerClass" :disabled="busy" @click="remove(row)">Delete</button>
          </div>
        </div>
        <dl class="mt-4 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt class="text-ink-400">Endpoint</dt>
            <dd class="mt-1 break-all font-mono">{{ row.host }}:{{ row.port }}</dd>
          </div>
          <div>
            <dt class="text-ink-400">Username</dt>
            <dd class="mt-1 flex items-center gap-2">
              <span class="break-all font-mono">{{ row.username }}</span>
              <button :class="ghostClass" @click="copy(row.username)">Copy</button>
            </dd>
          </div>
          <div>
            <dt class="text-ink-400">Connections from</dt>
            <dd class="mt-1">{{ row.remote === "%" ? "Anywhere (%)" : row.remote }}</dd>
          </div>
          <div>
            <dt class="text-ink-400">Password</dt>
            <dd class="mt-1 flex flex-wrap items-center gap-2">
              <span class="break-all font-mono">{{ isShown(row.id) ? row.password : "••••••••••••" }}</span>
              <button :class="ghostClass" @click="toggle(row.id)">{{ isShown(row.id) ? "Hide" : "Show" }}</button>
              <button :class="ghostClass" @click="copy(row.password)">Copy</button>
            </dd>
          </div>
        </dl>
      </div>
    </div>

    <div v-if="showForm" class="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" @click.self="showForm = false">
      <form class="w-full max-w-md rounded-xl border border-ink-700 bg-ink-900 p-6" @submit.prevent="create">
        <div class="flex items-center justify-between">
          <h3 class="text-xl font-semibold">Create new database</h3>
          <button type="button" class="text-ink-300 hover:text-accent-400" aria-label="Close" @click="showForm = false">✕</button>
        </div>
        <label class="mt-5 block text-sm text-ink-300" for="db-name">Database name</label>
        <input id="db-name" v-model="form.name" :class="inputClass" maxlength="32" autocomplete="off" />
        <p class="mt-2 text-xs text-ink-400">A descriptive name. Letters, numbers and underscores only.</p>
        <label class="mt-5 block text-sm text-ink-300" for="db-remote">Connections from</label>
        <input id="db-remote" v-model="form.remote" :class="inputClass" maxlength="255" autocomplete="off" />
        <p class="mt-2 text-xs text-ink-400">Where connections are allowed from. Leave blank to allow connections from anywhere.</p>
        <p v-if="formError" class="mt-4 rounded-md border border-bad/50 bg-bad/10 px-3 py-2 text-sm text-bad">{{ formError }}</p>
        <div class="mt-6 flex justify-end">
          <button type="submit" :class="primaryClass" :disabled="busy || !form.name.trim()">Create Database</button>
        </div>
      </form>
    </div>
  </div>
</template>
