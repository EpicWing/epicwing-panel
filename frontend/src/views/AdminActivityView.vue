<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import UserAvatar from "../components/UserAvatar.vue";

interface Item {
  id: string;
  created_at: string;
  action: string;
  actor: string | null;
  actor_id?: string | null;
  ip: string | null;
  target_type: string | null;
  target_id: string | null;
  details: Record<string, unknown> | null;
}

interface Page {
  items: Item[];
  has_more: boolean;
}

interface Filters {
  groups: string[];
  since: string;
  until: string;
  q: string;
}

const PAGE_SIZE = 50;
const GROUP_OPTIONS: [string, string][] = [
  ["security", "Security (failed logins)"],
  ["logins", "Logins"],
  ["users", "Users"],
  ["keys", "API and SSH keys"],
  ["nodes", "Nodes"],
  ["eggs", "Eggs"],
  ["servers", "Servers"],
];

const items = ref<Item[]>([]);
const hasMore = ref(false);
const loading = ref(true);
const loadingMore = ref(false);
const exporting = ref(false);
const showFilters = ref(false);
const error = ref("");

const draft = reactive<Filters>({ groups: [], since: "", until: "", q: "" });
const applied = ref<Filters>({ groups: [], since: "", until: "", q: "" });

const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const filterCount = computed(() => {
  const f = applied.value;
  return f.groups.length + (f.since ? 1 : 0) + (f.until ? 1 : 0) + (f.q.trim() ? 1 : 0);
});

const inputClass =
  "rounded-md border border-ink-700 bg-ink-950 px-3 py-1.5 text-sm outline-none transition focus:border-accent-500";
const buttonClass =
  "rounded-lg border border-ink-700 px-3 py-1.5 text-xs text-ink-200 transition hover:border-accent-500 disabled:opacity-40";

function name(item: Item): string {
  return item.actor ? item.actor.split("@")[0] : "System";
}

function failed(item: Item): boolean {
  return item.action.includes("failed");
}

function target(item: Item): string {
  if (!item.target_type) return "";
  const id = item.target_id ? `:${item.target_id.slice(0, 8)}` : "";
  return `${item.target_type}${id}`;
}

function details(item: Item): string[] {
  const out: string[] = [];
  for (const [key, value] of Object.entries(item.details ?? {})) {
    if ((typeof value === "string" && value) || typeof value === "number") {
      out.push(`${key}: ${value}`);
    } else if (Array.isArray(value) && value.length > 0) {
      out.push(`${key}: ${value.join(", ")}`);
    }
  }
  return out.slice(0, 4);
}

function when(value: string): string {
  return new Date(value).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

function ago(value: string): string {
  const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
  if (Math.abs(seconds) >= 30 * 86400) return new Date(value).toLocaleDateString("en-GB", { dateStyle: "medium" });
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

function query(extra: Record<string, string>): string {
  const params = new URLSearchParams(extra);
  const f = applied.value;
  for (const group of f.groups) params.append("groups", group);
  if (f.since) params.set("since", f.since);
  if (f.until) params.set("until", f.until);
  if (f.q.trim()) params.set("q", f.q.trim());
  return params.toString();
}

function page(offset: number): Promise<Page> {
  return api<Page>(`/audit-logs/events?${query({ limit: String(PAGE_SIZE), offset: String(offset) })}`);
}

async function load(): Promise<void> {
  error.value = "";
  loading.value = true;
  try {
    const first = await page(0);
    items.value = first.items;
    hasMore.value = first.has_more;
  } catch (cause) {
    items.value = [];
    hasMore.value = false;
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

function apply(): void {
  applied.value = { groups: [...draft.groups], since: draft.since, until: draft.until, q: draft.q };
  void load();
}

function clear(): void {
  draft.groups = [];
  draft.since = "";
  draft.until = "";
  draft.q = "";
  apply();
}

async function exportAs(format: "csv" | "json"): Promise<void> {
  exporting.value = true;
  error.value = "";
  try {
    const response = await fetch(`/api/audit-logs/events/export?${query({ format })}`, {
      credentials: "same-origin",
    });
    if (!response.ok) {
      let text = `Export failed (${response.status}).`;
      try {
        const data = await response.json();
        if (typeof data.detail === "string") text = data.detail;
      } catch {
        // Not a JSON response, the general message stays.
      }
      throw new ApiError(response.status, text);
    }
    const blob = await response.blob();
    const match = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "");
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = match ? match[1] : `activity.${format}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (cause) {
    error.value = message(cause);
  } finally {
    exporting.value = false;
  }
}

onMounted(load);
</script>

<template>
  <AppLayout area="admin" title="Activity" subtitle="Everything that happened in the panel: logins, users, keys, nodes, eggs and servers.">
    <div class="rounded-xl border border-ink-700 bg-ink-900">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-ink-700 px-5 py-3">
        <h3 class="text-lg font-semibold">Events <span v-if="!loading && !error" class="ml-1 text-sm font-normal text-ink-400">({{ items.length }}{{ hasMore ? "+" : "" }} events)</span></h3>
        <div class="flex flex-wrap items-center gap-2">
          <button :class="buttonClass" @click="showFilters = !showFilters">Filters<span v-if="filterCount" class="ml-1.5 rounded-full bg-accent-500 px-1.5 text-[10px] font-semibold text-ink-950">{{ filterCount }}</span></button>
          <button :class="buttonClass" :disabled="exporting" @click="exportAs('csv')">Export CSV</button>
          <button :class="buttonClass" :disabled="exporting" @click="exportAs('json')">Export JSON</button>
          <button :class="buttonClass" :disabled="loading" @click="load">Refresh</button>
        </div>
      </div>

      <div v-if="showFilters" class="space-y-4 border-b border-ink-800 px-5 py-4">
        <div class="flex flex-wrap gap-x-5 gap-y-2">
          <label v-for="[key, text] in GROUP_OPTIONS" :key="key" class="flex items-center gap-2 text-sm text-ink-200">
            <input v-model="draft.groups" type="checkbox" :value="key" class="accent-accent-500" />{{ text }}
          </label>
        </div>
        <div class="flex flex-wrap items-end gap-4">
          <label class="text-xs text-ink-400">From<input v-model="draft.since" type="date" :class="[inputClass, 'mt-1 block']" /></label>
          <label class="text-xs text-ink-400">To<input v-model="draft.until" type="date" :class="[inputClass, 'mt-1 block']" /></label>
          <label class="min-w-[12rem] flex-1 text-xs text-ink-400">Search<input v-model="draft.q" type="text" maxlength="100" placeholder="User, action or detail" :class="[inputClass, 'mt-1 block w-full']" @keyup.enter="apply" /></label>
        </div>
        <div class="flex gap-2">
          <button :class="buttonClass" :disabled="loading" @click="apply">Apply</button>
          <button :class="buttonClass" :disabled="loading" @click="clear">Reset filters</button>
        </div>
      </div>

      <p v-if="error" class="px-5 py-4 text-sm text-bad">{{ error }}</p>
      <div v-else-if="loading" class="space-y-3 px-5 py-5" aria-busy="true"><div class="skeleton h-10"></div><div class="skeleton h-10"></div><div class="skeleton h-10"></div><div class="skeleton h-10"></div></div>
      <p v-else-if="items.length === 0" class="px-5 py-10 text-center text-sm text-ink-500">{{ filterCount ? "No events match the filters." : "No activity events found." }}</p>
      <ul v-else class="divide-y divide-ink-800">
        <li v-for="item in items" :key="item.id" class="flex items-start gap-3 px-5 py-3">
          <UserAvatar class="mt-0.5" :user-id="item.actor_id" :label="name(item)" :size="32" />
          <div class="min-w-0">
            <p class="flex flex-wrap items-center gap-2 text-sm">
              <span class="font-semibold text-ink-100" :title="item.actor ?? ''">{{ name(item) }}</span>
              <span class="text-ink-500">•</span>
              <span class="rounded px-2 py-0.5 font-mono text-xs" :class="failed(item) ? 'bg-bad/20 text-bad' : 'bg-ink-800 text-ink-200'">{{ item.action }}</span>
              <span v-if="target(item)" class="font-mono text-xs text-ink-400">{{ target(item) }}</span>
            </p>
            <p class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-400">
              <span v-if="item.ip" class="rounded bg-ink-800 px-1.5 py-0.5 font-mono">{{ item.ip }}</span>
              <span :title="when(item.created_at)">{{ ago(item.created_at) }}</span>
              <span v-for="entry in details(item)" :key="entry" class="break-all">{{ entry }}</span>
            </p>
          </div>
        </li>
      </ul>
      <div v-if="hasMore && !loading" class="border-t border-ink-800 px-5 py-3 text-center">
        <button :class="buttonClass" :disabled="loadingMore" @click="more">{{ loadingMore ? "Loading…" : "Show more" }}</button>
      </div>
    </div>
  </AppLayout>
</template>
