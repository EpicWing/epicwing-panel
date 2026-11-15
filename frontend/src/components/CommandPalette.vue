<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { api } from "../api/client";
import { useTheme } from "../composables/useTheme";
import { auth } from "../stores/auth";

interface Item {
  id: string;
  group: string;
  label: string;
  hint?: string;
  keywords?: string;
  status?: string;
  run: () => void;
}

interface ServerRow {
  id: string;
  name: string;
  status: string;
  allocations?: { ip: string; port: number; is_primary: boolean }[];
}

interface NodeRow {
  id: string;
  name: string;
  status?: string;
  fqdn?: string | null;
}

const USER_PAGES = [
  { label: "Servers", to: "/", keywords: "home dashboard" },
  { label: "API keys", to: "/api-keys", keywords: "token" },
  { label: "SSH keys", to: "/ssh-keys", keywords: "sftp" },
  { label: "Settings", to: "/settings", keywords: "account password 2fa theme" },
];

const ADMIN_PAGES = [
  { label: "Admin overview", to: "/admin", keywords: "dashboard" },
  { label: "Nodes", to: "/admin/nodes", keywords: "agent machines" },
  { label: "Locations", to: "/admin/locations", keywords: "regions" },
  { label: "Database hosts", to: "/admin/databases", keywords: "mysql mariadb" },
  { label: "Backup storage", to: "/admin/storage", keywords: "s3 r2 b2 bucket cloud" },
  { label: "All servers", to: "/admin/servers", keywords: "create" },
  { label: "Nests & Eggs", to: "/admin/eggs", keywords: "templates import" },
  { label: "Marketplace", to: "/admin/marketplace", keywords: "plugins templates catalog" },
  { label: "Users", to: "/admin/users", keywords: "accounts" },
  { label: "Notifications", to: "/admin/notifications", keywords: "discord email mail" },
  { label: "Activity", to: "/admin/activity", keywords: "audit log" },
  { label: "Guide", to: "/admin/guide", keywords: "help docs" },
];

const router = useRouter();
const { setTheme } = useTheme();

const open = ref(false);
const query = ref("");
const active = ref(0);
const input = ref<HTMLInputElement | null>(null);
const servers = ref<ServerRow[]>([]);
const nodes = ref<NodeRow[]>([]);
let loadedAt = 0;
let returnFocus: HTMLElement | null = null;

const isAdmin = computed(() => !!auth.state.user?.is_admin);
const shortcut = /Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌘K" : "Ctrl K";

function go(to: string): void {
  void router.push(to);
}

function address(server: ServerRow): string {
  const list = server.allocations ?? [];
  const main = list.find((a) => a.is_primary) ?? list[0];
  return main ? `${main.ip}:${main.port}` : "";
}

const items = computed<Item[]>(() => {
  const list: Item[] = servers.value.map((s) => ({
    id: "server:" + s.id,
    group: "Server",
    label: s.name,
    hint: address(s),
    status: s.status,
    run: () => go(`/servers/${s.id}`),
  }));
  for (const page of USER_PAGES) {
    list.push({ id: "page:" + page.to, group: "Page", label: page.label, keywords: page.keywords, run: () => go(page.to) });
  }
  if (isAdmin.value) {
    for (const page of ADMIN_PAGES) {
      list.push({ id: "page:" + page.to, group: "Admin", label: page.label, keywords: page.keywords, run: () => go(page.to) });
    }
    for (const node of nodes.value) {
      list.push({
        id: "node:" + node.id,
        group: "Node",
        label: node.name,
        hint: node.fqdn ?? "",
        run: () => go(`/admin/nodes/${node.id}`),
      });
    }
  }
  list.push(
    { id: "theme:dark", group: "Action", label: "Dark theme", keywords: "appearance", run: () => setTheme("dark") },
    { id: "theme:light", group: "Action", label: "Light theme", keywords: "appearance", run: () => setTheme("light") },
    { id: "theme:system", group: "Action", label: "System theme", keywords: "appearance", run: () => setTheme("system") },
    {
      id: "logout",
      group: "Action",
      label: "Sign out",
      keywords: "logout",
      run: () => {
        void auth.logout().finally(() => router.push({ name: "login" }));
      },
    },
  );
  return list;
});

// Exact start beats a word inside, which beats letters in order ("mcs" finds "Minecraft Survival").
function score(item: Item, q: string): number {
  if (!q) return 1;
  const label = item.label.toLowerCase();
  const text = `${label} ${item.hint ?? ""} ${item.keywords ?? ""}`.toLowerCase();
  if (label.startsWith(q)) return 100;
  if (label.includes(q)) return 80;
  if (text.includes(q)) return 60;
  let from = 0;
  let last = -1;
  let gaps = 0;
  for (const ch of q) {
    if (ch === " ") continue;
    const found = text.indexOf(ch, from);
    if (found < 0) return 0;
    if (last >= 0) gaps += found - last - 1;
    last = found;
    from = found + 1;
  }
  return Math.max(1, 40 - gaps);
}

const results = computed<Item[]>(() => {
  const q = query.value.trim().toLowerCase();
  const scored = items.value.map((item) => ({ item, value: score(item, q) })).filter((r) => r.value > 0);
  if (q) scored.sort((a, b) => b.value - a.value);
  return scored.slice(0, 50).map((r) => r.item);
});

function dot(status: string): string {
  if (status === "running") return "bg-ok";
  if (["starting", "stopping", "installing"].includes(status)) return "bg-warn";
  if (status === "offline" || status === "error") return "bg-bad";
  return "bg-ink-500";
}

async function load(): Promise<void> {
  if (Date.now() - loadedAt < 30_000) return;
  loadedAt = Date.now();
  try {
    servers.value = await api<ServerRow[]>("/servers");
    if (isAdmin.value) nodes.value = await api<NodeRow[]>("/nodes");
  } catch {
    // Pages and actions still work without the lists.
    loadedAt = 0;
  }
}

function show(): void {
  returnFocus = document.activeElement as HTMLElement | null;
  open.value = true;
  query.value = "";
  active.value = 0;
  void load();
  void nextTick(() => input.value?.focus());
}

function hide(): void {
  open.value = false;
  returnFocus?.focus?.();
}

function run(item: Item): void {
  open.value = false;
  item.run();
}

function onKey(event: KeyboardEvent): void {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (open.value) hide();
    else show();
    return;
  }
  if (!open.value) return;
  const count = results.value.length;
  if (event.key === "Escape") {
    event.preventDefault();
    hide();
  } else if (event.key === "ArrowDown" && count) {
    event.preventDefault();
    active.value = (active.value + 1) % count;
  } else if (event.key === "ArrowUp" && count) {
    event.preventDefault();
    active.value = (active.value - 1 + count) % count;
  } else if (event.key === "Enter") {
    event.preventDefault();
    const item = results.value[active.value];
    if (item) run(item);
  }
}

watch(query, () => {
  active.value = 0;
});
watch(active, (index) => {
  void nextTick(() => document.getElementById(`cmd-${index}`)?.scrollIntoView({ block: "nearest" }));
});

onMounted(() => {
  window.addEventListener("keydown", onKey);
  window.addEventListener("epicwing:palette", show);
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("epicwing:palette", show);
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-[12vh]"
      @mousedown.self="hide"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search"
        class="w-full max-w-xl overflow-hidden rounded-xl border border-ink-700 bg-ink-900 shadow-2xl"
      >
        <div class="flex items-center gap-3 border-b border-ink-700 px-4">
          <svg viewBox="0 0 24 24" class="h-4 w-4 shrink-0 text-ink-500" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
            <path d="m21 21-4.3-4.3M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z" />
          </svg>
          <input
            ref="input"
            v-model="query"
            role="combobox"
            aria-expanded="true"
            aria-controls="cmd-list"
            :aria-activedescendant="results.length ? `cmd-${active}` : undefined"
            placeholder="Search servers, pages and actions"
            class="h-12 min-w-0 flex-1 bg-transparent text-sm text-ink-100 outline-none placeholder:text-ink-500"
          />
          <kbd class="rounded border border-ink-700 px-1.5 font-mono text-[11px] text-ink-500">Esc</kbd>
        </div>
        <ul id="cmd-list" role="listbox" class="max-h-[50vh] overflow-y-auto p-1.5">
          <li
            v-for="(item, i) in results"
            :id="`cmd-${i}`"
            :key="item.id"
            role="option"
            :aria-selected="i === active"
            class="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm"
            :class="i === active ? 'bg-ink-800 text-ink-100' : 'text-ink-300'"
            @mousemove="active = i"
            @click="run(item)"
          >
            <span class="h-2 w-2 shrink-0 rounded-full" :class="item.status ? dot(item.status) : ''" />
            <span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
            <span v-if="item.hint" class="hidden truncate font-mono text-xs text-ink-500 sm:block">{{ item.hint }}</span>
            <span class="w-12 shrink-0 text-right text-[11px] text-ink-500">{{ item.group }}</span>
          </li>
          <li v-if="!results.length" class="px-3 py-8 text-center text-sm text-ink-500">Nothing found</li>
        </ul>
        <div class="flex gap-4 border-t border-ink-700 px-4 py-2 text-[11px] text-ink-500">
          <span>↑ ↓ move</span>
          <span>Enter open</span>
          <span class="ml-auto">{{ shortcut }} toggle</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
