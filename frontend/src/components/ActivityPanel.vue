<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";

interface Item {
  id: string;
  created_at: string;
  action: string;
  actor: string | null;
  ip: string | null;
  details: Record<string, unknown> | null;
}

interface Page {
  items: Item[];
  has_more: boolean;
}

const props = defineProps<{ serverId: string; permissions: string[] }>();

const PAGE_SIZE = 50;
const items = ref<Item[]>([]);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref("");

const canView = computed(() => props.permissions.includes("settings.view"));

const LABELS: Record<string, string> = {
  "server.create": "created the server",
  "server.file.download": "downloaded a file",
  "server.file.write": "saved a file",
  "server.file.delete": "deleted a file or folder",
  "server.file.rename": "renamed or moved a file",
  "server.file.folder": "created a folder",
  "server.backup.create": "created a backup",
  "server.backup.delete": "deleted a backup",
  "server.backup.restore": "restored a backup",
  "server.backup.download": "downloaded a backup",
};

function label(action: string): string {
  return LABELS[action] ?? action.replace(/^server\./, "").replace(/[._]/g, " ");
}

function detail(item: Item): string {
  const data = item.details;
  if (!data) return "";
  const parts: string[] = [];
  for (const key of ["path", "to", "backup"]) {
    const value = data[key];
    if (typeof value === "string" && value) parts.push(value);
  }
  return parts.join(" → ");
}

function when(value: string): string {
  return new Date(value).toLocaleString();
}

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "The panel is not reachable.";
}

function page(offset: number): Promise<Page> {
  return api<Page>(`/servers/${props.serverId}/activity?limit=${PAGE_SIZE}&offset=${offset}`);
}

async function load(): Promise<void> {
  error.value = "";
  if (!canView.value) {
    loading.value = false;
    return;
  }
  loading.value = true;
  try {
    const first = await page(0);
    items.value = first.items;
    hasMore.value = first.has_more;
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}

async function more(): Promise<void> {
  loadingMore.value = true;
  try {
    const next = await page(items.value.length);
    const known = new Set(items.value.map((item) => item.id));
    items.value = [...items.value, ...next.items.filter((item) => !known.has(item.id))];
    hasMore.value = next.has_more;
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loadingMore.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="rounded-xl border border-ink-700 bg-ink-900">
    <div class="flex items-center justify-between border-b border-ink-700 px-5 py-3">
      <h3 class="text-lg font-semibold">Events</h3>
      <button class="rounded-lg border border-ink-700 px-3 py-1.5 text-xs text-ink-200 transition hover:border-accent-500 disabled:opacity-40" :disabled="loading || !canView" @click="load">Refresh</button>
    </div>
    <p v-if="!canView" class="px-5 py-10 text-center text-sm text-ink-500">You do not have access to the activity of this server.</p>
    <p v-else-if="error" class="px-5 py-4 text-sm text-bad">{{ error }}</p>
    <p v-else-if="loading" class="px-5 py-10 text-center text-sm text-ink-500">Loading…</p>
    <p v-else-if="items.length === 0" class="px-5 py-10 text-center text-sm text-ink-500">No activity events found.</p>
    <ul v-else class="divide-y divide-ink-800">
      <li v-for="item in items" :key="item.id" class="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 px-5 py-3 text-sm">
        <div class="min-w-0">
          <p class="text-ink-100"><span class="font-semibold">{{ item.actor ?? "Unknown user" }}</span> <span class="text-ink-300">{{ label(item.action) }}</span></p>
          <p v-if="detail(item)" class="mt-0.5 truncate font-mono text-xs text-ink-400">{{ detail(item) }}</p>
        </div>
        <p class="shrink-0 text-xs text-ink-400">{{ when(item.created_at) }}<span v-if="item.ip" class="ml-3 font-mono">{{ item.ip }}</span></p>
      </li>
    </ul>
    <div v-if="canView && hasMore && !loading" class="border-t border-ink-800 px-5 py-3 text-center">
      <button class="rounded-lg border border-ink-700 px-4 py-1.5 text-xs text-ink-200 transition hover:border-accent-500 disabled:opacity-40" :disabled="loadingMore" @click="more">{{ loadingMore ? "Loading…" : "Show more" }}</button>
    </div>
  </div>
</template>
