<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import KeyEmptyState from "../components/KeyEmptyState.vue";
import Modal from "../components/Modal.vue";

interface KeyRow {
  id: string;
  name: string;
  prefix: string;
  read_only: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
}

const keys = ref<KeyRow[]>([]);
const loading = ref(true);
const error = ref("");
const formError = ref("");
const busy = ref(false);
const open = ref(false);
const name = ref("");
const readOnly = ref(false);
const expiresInDays = ref("");
const created = ref<{ name: string; token: string } | null>(null);
const copied = ref(false);

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-800 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const buttonClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100";
const cancelClass =
  "rounded-md bg-ink-800 px-4 py-2 text-sm text-ink-300 transition hover:text-ink-100";
const primaryClass =
  "rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "The panel is not reachable.";
}

function formatDate(value: string | null, empty: string): string {
  return value ? new Date(value).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : empty;
}

async function load(): Promise<void> {
  try {
    keys.value = await api<KeyRow[]>("/api-keys");
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}

function openModal(): void {
  name.value = "";
  readOnly.value = false;
  expiresInDays.value = "";
  created.value = null;
  formError.value = "";
  copied.value = false;
  open.value = true;
}

function onModalChange(value: boolean): void {
  open.value = value;
  if (!value) created.value = null;
}

async function create(): Promise<void> {
  if (busy.value || !name.value.trim()) return;
  busy.value = true;
  formError.value = "";
  try {
    const days = expiresInDays.value ? Number(expiresInDays.value) : null;
    const result = await api<KeyRow & { token: string }>("/api-keys", {
      method: "POST",
      body: { name: name.value.trim(), read_only: readOnly.value, expires_in_days: days },
    });
    created.value = { name: result.name, token: result.token };
    copied.value = false;
    await load();
  } catch (cause) {
    formError.value = message(cause);
  } finally {
    busy.value = false;
  }
}

async function remove(row: KeyRow): Promise<void> {
  if (!window.confirm(`Delete the API key "${row.name}"? Scripts that use it stop working.`)) return;
  error.value = "";
  try {
    await api<void>(`/api-keys/${row.id}`, { method: "DELETE" });
    keys.value = keys.value.filter((key) => key.id !== row.id);
  } catch (cause) {
    error.value = message(cause);
  }
}

async function copyToken(): Promise<void> {
  if (!created.value) return;
  try {
    await navigator.clipboard.writeText(created.value.token);
    copied.value = true;
  } catch {
    // Clipboard is not available, the token stays selectable.
  }
}

onMounted(() => void load());
</script>

<template>
  <AppLayout title="API Keys" subtitle="Keys let scripts and bots control your servers without a password." hide-header>
    <div class="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-3xl font-bold tracking-tight">API Keys</h1>
        <p class="mt-1 text-sm text-ink-400">Keys let scripts and bots control your servers without a password.</p>
      </div>
      <button type="button" :class="primaryClass" @click="openModal">+ Create API Key</button>
    </div>

    <p v-if="error" role="alert" class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>

    <div v-if="loading" class="space-y-3" aria-busy="true">
      <div v-for="n in 3" :key="n" class="skeleton h-16"></div>
    </div>
    <ul v-else-if="keys.length" class="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
      <li v-for="row in keys" :key="row.id" class="flex flex-wrap items-center justify-between gap-3 p-4">
        <div class="min-w-0">
          <p class="flex items-center gap-2 font-medium">
            <span class="truncate">{{ row.name }}</span>
            <span v-if="row.read_only" class="rounded bg-ink-700 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-300">Read only</span>
          </p>
          <p class="mt-1 font-mono text-xs text-ink-400">{{ row.prefix }}…</p>
        </div>
        <div class="text-xs text-ink-400">
          <p>Last used: {{ formatDate(row.last_used_at, "never") }}</p>
          <p>Expires: {{ formatDate(row.expires_at, "never") }}</p>
        </div>
        <button :class="buttonClass" @click="remove(row)">Delete</button>
      </li>
    </ul>
    <KeyEmptyState v-else title="No API keys yet" text="Create a key so your scripts and bots can control your servers without a password." />

    <Modal
      :model-value="open"
      :title="created ? 'API Key created' : 'Create API Key'"
      :dismissable="!created"
      @update:model-value="onModalChange"
    >
      <div v-if="created">
        <p class="text-sm">Key "{{ created.name }}" is ready.</p>
        <p class="mt-1 text-sm text-ink-300">Copy it now. It is shown only once and cannot be recovered.</p>
        <div class="mt-4 flex items-center gap-2">
          <code class="min-w-0 flex-1 select-all break-all rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-xs">{{ created.token }}</code>
          <button type="button" :class="buttonClass" @click="copyToken">{{ copied ? "Copied" : "Copy" }}</button>
        </div>
      </div>
      <form v-else id="api-key-form" class="grid gap-4" @submit.prevent="create">
        <p v-if="formError" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{{ formError }}</p>
        <div>
          <label for="key-name" class="mb-1.5 block text-sm text-ink-300">Name</label>
          <input id="key-name" v-model="name" required maxlength="64" :class="inputClass" />
          <p class="mt-1.5 text-xs text-ink-400">Pick a name you will recognise later, for example "Discord bot".</p>
        </div>
        <div>
          <label for="key-expiry" class="mb-1.5 block text-sm text-ink-300">Expires</label>
          <select id="key-expiry" v-model="expiresInDays" :class="inputClass">
            <option value="">Never</option>
            <option value="30">In 30 days</option>
            <option value="90">In 90 days</option>
            <option value="365">In 1 year</option>
          </select>
        </div>
        <label class="flex items-center gap-2 text-sm text-ink-300">
          <input v-model="readOnly" type="checkbox" class="h-4 w-4 accent-accent-500" />
          Read only (the key can look at servers but not change anything)
        </label>
      </form>
      <template #footer>
        <template v-if="created">
          <button type="button" :class="primaryClass" @click="onModalChange(false)">Done</button>
        </template>
        <template v-else>
          <button type="button" :class="cancelClass" @click="onModalChange(false)">Cancel</button>
          <button type="submit" form="api-key-form" :class="primaryClass" :disabled="busy || !name.trim()">
            <span v-if="busy" class="spinner mr-2"></span>Create Key
          </button>
        </template>
      </template>
    </Modal>
  </AppLayout>
</template>
