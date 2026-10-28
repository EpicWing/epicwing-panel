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
const MODE_KEYS = ["action", "signal", "power"];
const items = ref<Item[]>([]);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref("");

const canView = computed(() => props.permissions.includes("settings.view"));
const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

function mode(item: Item): string | null {
  if (item.action !== "server.power") return null;
  const data = item.details ?? {};
  const key = MODE_KEYS.find((name) => typeof data[name] === "string");
  return key ? (data[key] as string) : null;
}

function code(item: Item): string {
  const base = item.action.replace(".", ":");
  const power = mode(item);
  return power ? `${base}.${power}` : base;
}

function name(item: Item): string {
  return item.actor ? item.actor.split("@")[0] : "System";
}

function details(item: Item): string[] {
  const data = item.details;
  if (!data) return [];
  const skip = mode(item) ? MODE_KEYS : [];
  const out: string[] = [];
  for (const [key, value] of Object.entries(data)) {
    if (skip.includes(key)) continue;
    if ((typeof value === "string" && value) || typeof value === "number") out.push(`${key}: ${value}`);
  }
  return out.slice(0, 3);
}

function when(value: string): string {
  return new Date(value).toLocaleString();
}

function ago(value: string): string {
  const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
  if (Math.abs(seconds) >= 30 * 86400) return new Date(value).toLocaleDateString();
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return rtf.format(seconds, "second");
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
      <h3 class="text-lg font-semibold">Events <span v-if="canView && !loading && !error" class="ml-1 text-sm font-normal text-ink-400">({{ items.length }}{{ hasMore ? "+" : "" }} events)</span></h3>
      <button class="rounded-lg border border-ink-700 px-3 py-1.5 text-xs text-ink-200 transition hover:border-accent-500 disabled:opacity-40" :disabled="loading || !canView" @click="load">Refresh</button>
    </div>
    <p v-if="!canView" class="px-5 py-10 text-center text-sm text-ink-500">You do not have access to the activity of this server.</p>
    <p v-else-if="error" class="px-5 py-4 text-sm text-bad">{{ error }}</p>
    <p v-else-if="loading" class="px-5 py-10 text-center text-sm text-ink-500">Loading…</p>
    <p v-else-if="items.length === 0" class="px-5 py-10 text-center text-sm text-ink-500">No activity events found.</p>
    <ul v-else class="divide-y divide-ink-800">
      <li v-for="item in items" :key="item.id" class="flex items-start gap-3 px-5 py-3">
        <div class="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink-700 text-xs font-semibold uppercase text-ink-100">{{ name(item).charAt(0) }}</div>
        <div class="min-w-0">
          <p class="flex flex-wrap items-center gap-2 text-sm">
            <span class="font-semibold text-ink-100" :title="item.actor ?? ''">{{ name(item) }}</span>
            <span class="text-ink-500">•</span>
            <span class="rounded bg-ink-800 px-2 py-0.5 font-mono text-xs text-ink-200">{{ code(item) }}</span>
          </p>
          <p class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-400">
            <span v-if="item.ip" class="rounded bg-ink-800 px-1.5 py-0.5 font-mono">{{ item.ip }}</span>
            <span :title="when(item.created_at)">{{ ago(item.created_at) }}</span>
            <span v-for="entry in details(item)" :key="entry" class="break-all">{{ entry }}</span>
          </p>
        </div>
      </li>
    </ul>
    <div v-if="canView && hasMore && !loading" class="border-t border-ink-800 px-5 py-3 text-center">
      <button class="rounded-lg border border-ink-700 px-4 py-1.5 text-xs text-ink-200 transition hover:border-accent-500 disabled:opacity-40" :disabled="loadingMore" @click="more">{{ loadingMore ? "Loading…" : "Show more" }}</button>
    </div>
  </div>
</template>
