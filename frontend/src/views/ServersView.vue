<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import ContainerPanel from "../components/ContainerPanel.vue";
import ServerCard, { type ServerItem } from "../components/ServerCard.vue";
import { auth } from "../stores/auth";

const { t } = useI18n();

// Real servers do not exist yet, the list stays empty until the agent is built.
const servers = ref<ServerItem[]>([]);
const nodeCount = ref<number | null>(null);
const layout = ref<"grid" | "list">("grid");

// Demo data is only available in development and always labelled as such.
const demoAllowed = import.meta.env.DEV;
const showDemo = ref(false);
const demoServers: ServerItem[] = [
  { id: "d1", name: "Survival", address: "203.0.113.10:25565", status: "running", cpu: "8.8%", ram: "2 GiB", storage: "4 GiB", cpuPct: 9, ramPct: 48, diskPct: 22 },
  { id: "d2", name: "Creative", address: "203.0.113.10:25566", status: "running", cpu: "3.1%", ram: "1 GiB", storage: "2 GiB", cpuPct: 3, ramPct: 30, diskPct: 12 },
  { id: "d3", name: "Discord Bot", address: "203.0.113.10:6000", status: "starting", cpu: "0.2%", ram: "299 MiB", storage: "57 MiB", cpuPct: 1, ramPct: 15, diskPct: 2 },
  { id: "d4", name: "Test World", address: "203.0.113.10:27015", status: "offline", cpu: "0%", ram: "0 B", storage: "3 GiB", cpuPct: 0, ramPct: 0, diskPct: 35 },
];

function toggleClass(active: boolean): string {
  return active ? "bg-ink-800 text-accent-400" : "text-ink-400 hover:text-ink-100";
}

onMounted(async () => {
  if (!auth.state.user?.is_admin) {
    return;
  }
  try {
    nodeCount.value = (await api<unknown[]>("/nodes")).length;
  } catch {
    // Without permission or on an error the hint is simply not shown.
  }
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
      />
    </div>

    <ContainerPanel v-else-if="auth.state.user?.is_admin" />

    <div v-else class="rounded-lg border border-dashed border-ink-700 px-6 py-14 text-center">
      <p class="font-medium">{{ t("servers.emptyTitle") }}</p>
      <p class="mx-auto mt-1 max-w-md text-sm text-ink-400">{{ t("servers.emptyBody") }}</p>
      <p v-if="nodeCount !== null" class="mt-4 font-mono text-xs text-ink-400">
        {{ t("servers.nodesRegistered", { count: nodeCount }) }}
      </p>
    </div>
  </AppLayout>
</template>
