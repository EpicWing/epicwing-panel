<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { api, ApiError } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import ServerCard, { type ServerItem } from "../components/ServerCard.vue";
import { auth } from "../stores/auth";

const { t } = useI18n();
const router = useRouter();

// Real servers, loaded for admins. Live values come with the agent.
const servers = ref<ServerItem[]>([]);
const nodeCount = ref<number | null>(null);
const loadError = ref("");
const layout = ref<"grid" | "list">("grid");

interface ApiServer {
  id: string;
  name: string;
  status: string;
  memory_mb: number;
  cpus: number;
  disk_mb: number;
  live_cpu_percent?: number | null;
  live_memory_used_bytes?: number | null;
  live_disk_used_bytes?: number | null;
  allocations: { ip: string; port: number; is_primary: boolean }[];
}

function formatSize(mb: number): string {
  return mb >= 1024 ? `${+(mb / 1024).toFixed(1)} GiB` : `${mb} MiB`;
}

function formatBytes(bytes: number | null | undefined): string | null {
  if (bytes === null || bytes === undefined) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KiB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GiB`;
}

// Until the agent reports live usage, the cards show the configured limits.
function toCard(s: ApiServer): ServerItem {
  const main = s.allocations.find((a) => a.is_primary) ?? s.allocations[0];
  const status: ServerItem["status"] =
    s.status === "running" || s.status === "starting" ? s.status : "offline";
  return {
    id: s.id,
    name: s.name,
    address: main ? `${main.ip}:${main.port}` : "–",
    status,
    cpu: s.live_cpu_percent == null ? `${s.cpus} cores` : `${s.live_cpu_percent.toFixed(1)}%`,
    ram: formatBytes(s.live_memory_used_bytes) ?? formatSize(s.memory_mb),
    storage: formatBytes(s.live_disk_used_bytes) ?? formatSize(s.disk_mb),
  };
}

// Demo data is only available in development and always labelled as such.
const demoAllowed = import.meta.env.DEV;
const showDemo = ref(false);
const demoServers: ServerItem[] = [
  { id: "d1", name: "Survival", address: "203.0.113.10:25565", status: "running", cpu: "8.8%", ram: "2 GiB", storage: "4 GiB", cpuPct: 9, ramPct: 48, diskPct: 22 },
  { id: "d2", name: "Creative", address: "203.0.113.10:25566", status: "running", cpu: "3.1%", ram: "1 GiB", storage: "2 GiB", cpuPct: 3, ramPct: 30, diskPct: 12 },
  { id: "d3", name: "Discord Bot", address: "203.0.113.10:6000", status: "starting", cpu: "0.2%", ram: "299 MiB", storage: "57 MiB", cpuPct: 1, ramPct: 15, diskPct: 2 },
  { id: "d4", name: "Test World", address: "203.0.113.10:27015", status: "offline", cpu: "0%", ram: "0 B", storage: "3 GiB", cpuPct: 0, ramPct: 0, diskPct: 35 },
];
let refreshTimer: number | undefined;

function toggleClass(active: boolean): string {
  return active ? "bg-ink-800 text-accent-400" : "text-ink-400 hover:text-ink-100";
}

async function loadServers(): Promise<void> {
  if (auth.state.user?.is_admin) {
    try {
      nodeCount.value = (await api<unknown[]>("/nodes")).length;
    } catch {
      // Without permission or on an error the hint is simply not shown.
    }
  }
  try {
    servers.value = (await api<ApiServer[]>("/servers")).map(toCard);
    loadError.value = "";
  } catch (cause) {
    // Do not turn an authorization/backend failure into a misleading "no servers" state.
    loadError.value = cause instanceof ApiError
      ? `${cause.message} (${cause.status})`
      : cause instanceof Error
        ? cause.message
        : String(cause);
  }
}

onMounted(async () => {
  await loadServers();
  refreshTimer = window.setInterval(loadServers, 5000);
});

onBeforeUnmount(() => {
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer);
});
</script>

<template>
  <AppLayout wide :title="t('servers.title')" :subtitle="t('servers.subtitle')">
    <template #actions>
      <div class="flex items-center gap-2">
        <button
          v-if="demoAllowed"
          class="rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100"
          @click="showDemo = !showDemo"
        >
          {{ showDemo ? t("servers.hideDemo") : t("servers.showDemo") }}
        </button>
        <div class="flex overflow-hidden rounded-md border border-ink-700">
          <button
            class="px-2.5 py-1.5 transition"
            :class="toggleClass(layout === 'grid')"
            :title="t('servers.viewGrid')"
            :aria-label="t('servers.viewGrid')"
            @click="layout = 'grid'"
          >
            <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
            </svg>
          </button>
          <button
            class="border-l border-ink-700 px-2.5 py-1.5 transition"
            :class="toggleClass(layout === 'list')"
            :title="t('servers.viewList')"
            :aria-label="t('servers.viewList')"
            @click="layout = 'list'"
          >
            <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M4 6h16M4 12h16M4 18h16" stroke-linecap="round" />
            </svg>
          </button>
        </div>
      </div>
    </template>

    <p v-if="showDemo" class="mb-4 text-xs text-ink-400">{{ t("servers.demoNotice") }}</p>

    <div v-if="loadError" class="mb-4 rounded-lg border border-red-900/70 bg-red-950/30 px-4 py-3 text-sm text-red-200">
      <p class="font-medium">Could not load the server list.</p>
      <p class="mt-1 text-red-300/80">{{ loadError }}</p>
    </div>

    <div
      v-if="showDemo || servers.length > 0"
      :class="layout === 'grid' ? 'grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4' : 'flex flex-col gap-3'"
    >
      <ServerCard
        v-for="server in showDemo ? demoServers : servers"
        :key="server.id"
        :server="server"
        :demo="showDemo"
        :layout="layout"
        @open="router.push(`/servers/${$event}`)"
      />
    </div>

    <div v-else-if="!loadError" class="rounded-lg border border-dashed border-ink-700 px-6 py-14 text-center">
      <p class="font-medium">{{ t("servers.emptyTitle") }}</p>
      <p class="mx-auto mt-1 max-w-md text-sm text-ink-400">{{ t("servers.emptyBody") }}</p>
      <p v-if="nodeCount !== null" class="mt-4 font-mono text-xs text-ink-400">
        {{ t("servers.nodesRegistered", { count: nodeCount }) }}
      </p>
    </div>
  </AppLayout>
</template>
