<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { ApiError, api } from "../api/client";
import UserAvatar from "./UserAvatar.vue";

interface Item {
  id: string;
  created_at: string;
  action: string;
  actor: string | null;
  actor_id?: string | null;
  ip: string | null;
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

const props = defineProps<{ serverId: string; permissions: string[] }>();

const PAGE_SIZE = 50;
const MODE_KEYS = ["action", "signal", "power"];
const HIDDEN_KEYS = ["name", "allocation", "ip", "port"];
const GROUP_OPTIONS: [string, string][] = [
  ["power", "Power"],
  ["files", "Files"],
  ["backups", "Backups"],
  ["ports", "Ports"],
  ["server", "Server"],
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

const canView = computed(() => props.permissions.includes("settings.view"));
const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
const filterCount = computed(() => {
  const f = applied.value;
  return f.groups.length + (f.since ? 1 : 0) + (f.until ? 1 : 0) + (f.q.trim() ? 1 : 0);
});

const inputClass =
  "rounded-md border border-ink-700 bg-ink-950 px-3 py-1.5 text-sm outline-none transition focus:border-accent-500";
const buttonClass =
  "rounded-lg border border-ink-700 px-3 py-1.5 text-xs text-ink-200 transition hover:border-accent-500 disabled:opacity-40";

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
  if (typeof data.ip === "string" && typeof data.port === "number") {
    out.push(`allocation: ${data.ip}:${data.port}`);
  }
  for (const [key, value] of Object.entries(data)) {
    if (skip.includes(key) || HIDDEN_KEYS.includes(key)) continue;
    if ((typeof value === "string" && value) || typeof value === "number") {
      out.push(`${key}: ${value}`);
    } else if (Array.isArray(value) && value.length > 0) {
      out.push(`${key}: ${value.join(", ")}`);
    } else if (value && typeof value === "object") {
      const parts = Object.entries(value as Record<string, unknown>)
        .filter(([, v]) => (Array.isArray(v) ? v.length > 0 : v !== "" && v != null))
        .map(([name, v]) => `${name}=${Array.isArray(v) ? v.join(", ") : String(v)}`);
      if (parts.length > 0) out.push(`${key}: ${parts.join(", ")}`);
    }
  }
  return out.slice(0, 3);
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
  const qs = query({ limit: String(PAGE_SIZE), offset: String(offset) });
  return api<Page>(`/servers/${props.serverId}/activity?${qs}`);
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
    const response = await fetch(
      `/api/servers/${props.serverId}/activity/export?${query({ format })}`,
      { credentials: "same-origin" },
    );
    if (!response.ok) {
      let text = `Export failed (${response.status}).`;
      try {
        const data = await response.json();
        if (typeof data.detail === "string") text = data.detail;
      } catch {
        // Keine JSON-Antwort, die allgemeine Meldung bleibt.
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
  <div class="rounded-xl border border-ink-700 bg-ink-900">
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-ink-700 px-5 py-3">
      <h3 class="text-lg font-semibold">Events <span v-if="canView && !loading && !error" class="ml-1 text-sm font-normal text-ink-400">({{ items.length }}{{ hasMore ? "+" : "" }} events)</span></h3>
      <div class="flex flex-wrap items-center gap-2">
        <button :class="buttonClass" :disabled="!canView" @click="showFilters = !showFilters">Filters<span v-if="filterCount" class="ml-1.5 rounded-full bg-accent-500 px-1.5 text-[10px] font-semibold text-white">{{ filterCount }}</span></button>
        <button :class="buttonClass" :disabled="!canView || exporting" @click="exportAs('csv')">Export CSV</button>
        <button :class="buttonClass" :disabled="!canView || exporting" @click="exportAs('json')">Export JSON</button>
        <button :class="buttonClass" :disabled="loading || !canView" @click="load">Refresh</button>
      </div>
    </div>

    <div v-if="canView && showFilters" class="space-y-4 border-b border-ink-800 px-5 py-4">
      <div class="flex flex-wrap gap-x-5 gap-y-2">
        <label v-for="[key, text] in GROUP_OPTIONS" :key="key" class="flex items-center gap-2 text-sm text-ink-200">
          <input v-model="draft.groups" type="checkbox" :value="key" class="accent-accent-500" />{{ text }}
        </label>
      </div>
      <div class="flex flex-wrap items-end gap-4">
        <label class="text-xs text-ink-400">From<input v-model="draft.since" type="date" :class="[inputClass, 'mt-1 block']" /></label>
        <label class="text-xs text-ink-400">To<input v-model="draft.until" type="date" :class="[inputClass, 'mt-1 block']" /></label>
        <label class="min-w-[12rem] flex-1 text-xs text-ink-400">Search<input v-model="draft.q" type="text" maxlength="100" placeholder="User, action or path" :class="[inputClass, 'mt-1 block w-full']" @keyup.enter="apply" /></label>
      </div>
      <div class="flex gap-2">
        <button :class="buttonClass" :disabled="loading" @click="apply">Apply</button>
        <button :class="buttonClass" :disabled="loading" @click="clear">Reset filters</button>
      </div>
    </div>

    <p v-if="!canView" class="px-5 py-10 text-center text-sm text-ink-500">You do not have access to the activity of this server.</p>
    <p v-else-if="error" class="px-5 py-4 text-sm text-bad">{{ error }}</p>
    <div v-else-if="loading" class="space-y-3 px-5 py-5" aria-busy="true"><div class="skeleton h-10"></div><div class="skeleton h-10"></div><div class="skeleton h-10"></div><div class="skeleton h-10"></div></div>
    <p v-else-if="items.length === 0" class="px-5 py-10 text-center text-sm text-ink-500">{{ filterCount ? "No events match the filters." : "No activity events found." }}</p>
    <ul v-else class="divide-y divide-ink-800">
      <li v-for="item in items" :key="item.id" class="flex items-start gap-3 px-5 py-3">
        <UserAvatar class="mt-0.5" :user-id="item.actor_id" :label="name(item)" :size="32" />
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
      <button :class="buttonClass" :disabled="loadingMore" @click="more">{{ loadingMore ? "Loading…" : "Show more" }}</button>
    </div>
  </div>
</template>
