<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

interface KeyRow {
  id: string;
  name: string;
  key_type: string;
  fingerprint: string;
  last_used_at: string | null;
  created_at: string;
}

const keys = ref<KeyRow[]>([]);
const loading = ref(true);
const error = ref("");
const busy = ref(false);
const name = ref("");
const publicKey = ref("");

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const buttonClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100";
const primaryClass =
  "rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "The panel is not reachable.";
}

function formatDate(value: string | null, empty: string): string {
  return value ? new Date(value).toLocaleString() : empty;
}

async function load(): Promise<void> {
  try {
    keys.value = await api<KeyRow[]>("/ssh-keys");
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}

async function add(): Promise<void> {
  if (busy.value || !name.value.trim() || !publicKey.value.trim()) return;
  busy.value = true;
  error.value = "";
  try {
    await api<KeyRow>("/ssh-keys", {
      method: "POST",
      body: { name: name.value.trim(), public_key: publicKey.value.trim() },
    });
    name.value = "";
    publicKey.value = "";
    await load();
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

async function remove(row: KeyRow): Promise<void> {
  if (!window.confirm(`Delete the SSH key "${row.name}"?`)) return;
  error.value = "";
  try {
    await api<void>(`/ssh-keys/${row.id}`, { method: "DELETE" });
    keys.value = keys.value.filter((key) => key.id !== row.id);
  } catch (cause) {
    error.value = message(cause);
  }
}

onMounted(() => void load());
</script>

<template>
  <AppLayout title="SSH Keys" subtitle="Public keys for SFTP access to your server files.">
    <p v-if="error" role="alert" class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>

    <form class="mb-6 grid gap-4 rounded-xl border border-ink-700 bg-ink-900 p-5" @submit.prevent="add">
      <div>
        <label for="ssh-name" class="mb-1.5 block text-sm text-ink-300">Name</label>
        <input id="ssh-name" v-model="name" required maxlength="64" placeholder="My laptop" :class="inputClass" />
      </div>
      <div>
        <label for="ssh-key" class="mb-1.5 block text-sm text-ink-300">Public key</label>
        <textarea id="ssh-key" v-model="publicKey" required rows="3" placeholder="ssh-ed25519 AAAA..." :class="inputClass + ' font-mono text-xs'"></textarea>
        <p class="mt-1.5 text-xs text-ink-400">Paste the content of your .pub file, never the private key.</p>
      </div>
      <div>
        <button type="submit" :class="primaryClass" :disabled="busy || !name.trim() || !publicKey.trim()">
          <span v-if="busy" class="spinner mr-2"></span>Add key
        </button>
      </div>
    </form>

    <div v-if="loading" class="space-y-3" aria-busy="true">
      <div v-for="n in 3" :key="n" class="skeleton h-16"></div>
    </div>
    <ul v-else-if="keys.length" class="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
      <li v-for="row in keys" :key="row.id" class="flex flex-wrap items-center justify-between gap-3 p-4">
        <div class="min-w-0">
          <p class="truncate font-medium">{{ row.name }}</p>
          <p class="mt-1 break-all font-mono text-xs text-ink-400">{{ row.fingerprint }}</p>
        </div>
        <div class="text-xs text-ink-400">
          <p>{{ row.key_type }}</p>
          <p>Last used: {{ formatDate(row.last_used_at, "never") }}</p>
        </div>
        <button :class="buttonClass" @click="remove(row)">Delete</button>
      </li>
    </ul>
    <div v-else class="rounded-lg border border-dashed border-ink-700 px-6 py-10 text-center text-sm text-ink-400">
      You have no SSH keys yet.
    </div>
  </AppLayout>
</template>
