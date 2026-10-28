<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import ConsoleOutput from "../components/ConsoleOutput.vue";
import FilesPanel from "../components/FilesPanel.vue";
import StartupPanel from "../components/StartupPanel.vue";
import { type ConsoleFrame, useServerConsole } from "../composables/useServerConsole";

interface Allocation {
  ip: string;
  port: number;
  is_primary: boolean;
}

interface ServerData {
  id: string;
  name: string;
  description: string;
  status: string;
  last_error: string | null;
  memory_mb: number;
  cpus: number;
  disk_mb: number;
  image: string;
  startup_command: string;
  node_name: string;
  egg_name: string;
  allocations: Allocation[];
}

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const server = ref<ServerData | null>(null);
const active = ref("home");
const command = ref("");
const error = ref("");
const metrics = ref({ cpu: 0, ram: 0, disk: 0, rx: 0, tx: 0 });
const history = ref({ cpu: [] as number[], ram: [] as number[], disk: [] as number[], rx: [] as number[], tx: [] as number[] });
let previousNetwork: { rx: number; tx: number; at: number } | null = null;

const groups = [
  { title: "Overview", items: [["home", "Home"], ["activity", "Timeline"]] },
  { title: "Manage", items: [["files", "Files"], ["startup", "Launch"], ["networking", "Ports"], ["schedules", "Automations"]] },
  { title: "Data", items: [["databases", "Databases"], ["backups", "Backups"]] },
  { title: "Admin", items: [["users", "Access"], ["settings", "Settings"]] },
] as const;

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : t("common.unreachable");
}

function formatBytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount >= 10 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
}

function pushHistory(key: keyof typeof history.value, value: number): void {
  const values = history.value[key];
  values.push(value);
  if (values.length > 60) values.shift();
}

function chartPoints(key: string): string {
  const values = history.value[key as keyof typeof history.value] ?? [];
  if (values.length < 2) return "0,72 300,72";
  const max = Math.max(...values, 1);
  return values.map((value, index) => `${(index / (values.length - 1)) * 300},${72 - (value / max) * 64}`).join(" ");
}

function networkPoints(key: "rx" | "tx"): string {
  return chartPoints(key)
    .split(" ")
    .map((point) => {
      const [x, y] = point.split(",");
      return `${Number(x) * 3},${y}`;
    })
    .join(" ");
}

function handleFrame(frame: ConsoleFrame): void {
  if (frame.type === "stats") {
    const stats = frame as ConsoleFrame & {
      cpu_percent: number;
      memory_used_bytes: number;
      disk_used_bytes: number;
      network_rx_bytes: number;
      network_tx_bytes: number;
    };
    const now = Date.now();
    let rxRate = 0;
    let txRate = 0;
    if (previousNetwork) {
      const seconds = Math.max(0.1, (now - previousNetwork.at) / 1000);
      rxRate = Math.max(0, (stats.network_rx_bytes - previousNetwork.rx) / seconds);
      txRate = Math.max(0, (stats.network_tx_bytes - previousNetwork.tx) / seconds);
    }
    previousNetwork = { rx: stats.network_rx_bytes, tx: stats.network_tx_bytes, at: now };
    metrics.value = { cpu: stats.cpu_percent, ram: stats.memory_used_bytes, disk: stats.disk_used_bytes, rx: rxRate, tx: txRate };
    pushHistory("cpu", stats.cpu_percent);
    pushHistory("ram", stats.memory_used_bytes);
    pushHistory("disk", stats.disk_used_bytes);
    pushHistory("rx", rxRate);
    pushHistory("tx", txRate);
  }
  if (frame.type === "status" && frame.status && server.value) server.value.status = frame.status;
}

const {
  lines,
  status: connection,
  error: consoleError,
  connect: connectConsole,
  send,
} = useServerConsole({ onFrame: handleFrame });

function sendCommand(): void {
  if (send(command.value)) command.value = "";
}

let statusTimer: number | undefined;

// Polls the stored status so the buttons never depend on a single websocket event.
async function refreshStatus(): Promise<void> {
  if (!server.value) return;
  try {
    const fresh = await api<ServerData>(`/servers/${server.value.id}`);
    if (server.value && server.value.id === fresh.id) server.value.status = fresh.status;
  } catch {
    // The next poll tries again.
  }
}

onMounted(() => {
  statusTimer = window.setInterval(() => void refreshStatus(), 3000);
});
onBeforeUnmount(() => window.clearInterval(statusTimer));

async function power(action: "start" | "restart" | "stop" | "kill"): Promise<void> {
  if (!server.value) return;
  try {
    server.value = await api<ServerData>(`/servers/${server.value.id}/power`, {
      method: "POST",
      body: { action },
    });
  } catch (cause) {
    error.value = message(cause);
  }
}

onMounted(async () => {
  try {
    server.value = await api<ServerData>(`/servers/${String(route.params.id)}`);
    await connectConsole(String(route.params.id));
  } catch (cause) {
    error.value = message(cause);
  }
});

</script>

<template>
  <AppLayout wide minimal hero :hide-header="active !== 'home'" :title="server?.name ?? 'Server'">
    <template #sidebar>
      <button class="mb-7 flex w-full items-center gap-2 px-3 py-2 text-sm text-ink-400 transition hover:text-ink-100" @click="router.push('/')">
        <span aria-hidden="true">←</span>
        Back to servers
      </button>
      <div v-for="group in groups" :key="group.title" class="mb-5 last:mb-0">
        <p class="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-wider text-ink-500">{{ group.title }}</p>
        <button
          v-for="item in group.items"
          :key="item[0]"
          class="mb-0.5 flex w-full items-center rounded-md px-3 py-2 text-left text-sm font-medium transition last:mb-0"
          :class="active === item[0] ? 'bg-accent-500/15 text-accent-300' : 'text-ink-200 hover:bg-ink-800 hover:text-ink-100'"
          @click="active = item[0]"
        >
          {{ item[1] }}
        </button>
      </div>
    </template>

    <template #sidebar-footer>
      <div class="mt-4 rounded-xl border border-ink-700 bg-ink-950 p-3">
        <p class="text-[10px] uppercase tracking-wider text-ink-400">Server</p>
        <p class="mt-1 truncate text-sm font-semibold text-ink-100">{{ server?.name || 'Server' }}</p>
      </div>
    </template>

    <template #actions>
      <div v-if="active === 'home'" class="flex overflow-hidden rounded-xl border border-ink-700 shadow-lg shadow-black/20">
        <button class="px-6 py-3 text-sm font-semibold text-ink-300 transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-40" :disabled="server?.status === 'running' || server?.status === 'starting'" @click="power('start')">Start</button>
        <button class="border-l border-ink-700 px-6 py-3 text-sm font-semibold text-ink-100 transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-40" :disabled="server?.status !== 'running' && server?.status !== 'starting'" @click="power('restart')">Restart</button>
        <button class="border-l border-accent-400/30 bg-accent-500 px-6 py-3 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-40" :disabled="server?.status !== 'running' && server?.status !== 'starting'" @click="power('stop')">Stop</button>
      </div>
    </template>

    <div v-if="server">
      <main class="min-w-0 space-y-3">
        <div v-if="active === 'home'" class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span class="inline-flex items-center gap-2 rounded-full border border-ink-700 bg-ink-900 px-3 py-1.5 text-sm font-medium text-ink-200 shadow-sm">
              <span class="h-2 w-2 rounded-full" :class="server.status === 'running' ? 'bg-ok' : server.status === 'starting' ? 'bg-warn' : 'bg-bad'" />
              {{ server.status === 'running' ? 'Running' : server.status === 'starting' ? 'Starting' : server.status === 'error' ? 'Error' : 'Offline' }}
            </span>
          </div>
          <span />
        </div>

        <div v-if="active === 'home'" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4"><p class="text-xs uppercase text-ink-400">IP address</p><p class="mt-2 truncate font-mono text-lg font-semibold">{{ server.allocations[0]?.ip }}:{{ server.allocations[0]?.port }}</p></div>
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4"><p class="text-xs uppercase text-ink-400">CPU usage</p><p class="mt-2 text-xl font-semibold">{{ metrics.cpu.toFixed(1) }}%</p></div>
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4"><p class="text-xs uppercase text-ink-400">RAM usage</p><p class="mt-2 text-xl font-semibold">{{ formatBytes(metrics.ram) }}</p></div>
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4"><p class="text-xs uppercase text-ink-400">Storage usage</p><p class="mt-2 text-xl font-semibold">{{ formatBytes(metrics.disk) }}</p></div>
        </div>

        <section v-if="active === 'home'" class="overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
          <ConsoleOutput :lines="lines" :placeholder="t('console.waiting')" class="h-[min(34vh,28rem)] min-h-[17rem]" />
          <p v-if="error || consoleError" class="border-t border-bad/30 bg-bad/10 px-4 py-2 text-xs text-bad">{{ error || consoleError }}</p>
          <form class="flex gap-2 border-t border-ink-700 p-3" @submit.prevent="sendCommand">
            <input v-model="command" class="min-w-0 flex-1 rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-sm outline-none focus:border-accent-500" placeholder="Enter a command…" :disabled="connection !== 'connected' && connection !== 'running'" autocomplete="off" />
            <button class="rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50" :disabled="!command.trim() || (connection !== 'connected' && connection !== 'running')">Send</button>
          </form>
        </section>

        <section v-if="active === 'home'" class="grid gap-4 lg:grid-cols-3">
          <div v-for="chart in [
            { key: 'cpu', title: 'CPU', value: `${metrics.cpu.toFixed(1)}%`, color: '#e5534b' },
            { key: 'ram', title: 'RAM', value: formatBytes(metrics.ram), color: '#d9a21b' },
          ]" :key="chart.key" class="rounded-xl border border-ink-700 bg-ink-900 p-4">
            <div class="flex items-center justify-between"><p class="flex items-center gap-2 text-xs uppercase tracking-wider text-ink-400"><span class="h-2 w-2 rounded-full" :style="{ backgroundColor: chart.color }"></span>{{ chart.title }}</p><p class="font-mono text-sm">{{ chart.value }}</p></div>
            <svg viewBox="0 0 300 80" class="mt-3 h-16 w-full" preserveAspectRatio="none" aria-hidden="true"><polyline :points="chartPoints(chart.key)" fill="none" :stroke="chart.color" stroke-width="2" vector-effect="non-scaling-stroke" /></svg>
          </div>
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
            <div class="flex items-center justify-between"><p class="text-xs uppercase tracking-wider text-ink-400">Network activity</p><p class="font-mono text-sm">↓ {{ formatBytes(metrics.rx) }}/s · ↑ {{ formatBytes(metrics.tx) }}/s</p></div>
            <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-400">
              <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full" style="background-color: #49c58a"></span>↓ Download (incoming)</span>
              <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full" style="background-color: #f778ba"></span>↑ Upload (outgoing)</span>
              <span class="text-ink-500">Each line is scaled to its own peak.</span>
            </div>
            <svg viewBox="0 0 900 80" class="mt-3 h-16 w-full" preserveAspectRatio="none" aria-hidden="true">
              <polyline :points="networkPoints('rx')" fill="none" stroke="#49c58a" stroke-width="2" vector-effect="non-scaling-stroke" />
              <polyline :points="networkPoints('tx')" fill="none" stroke="#f778ba" stroke-width="2" vector-effect="non-scaling-stroke" />
            </svg>
          </div>
        </section>

        <template v-else>
          <FilesPanel v-if="active === 'files'" :server-id="server.id" :status="server.status" />
          <div v-else-if="active === 'databases'" class="space-y-6">
            <div class="flex items-start justify-between gap-4"><div><h2 class="text-2xl font-semibold">Databases</h2><p class="mt-2 text-sm text-ink-400">Create and manage databases for your server and configure access details.</p></div><button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950">New Database</button></div>
            <div class="flex min-h-[24rem] items-center justify-center rounded-xl border border-ink-700 bg-ink-900 text-center"><div><div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-ink-800 text-2xl">▣</div><h3 class="text-lg font-semibold">No databases found</h3><p class="mt-2 text-sm text-ink-400">Your server does not have any databases yet.</p></div></div>
          </div>

          <div v-else-if="active === 'backups'" class="space-y-6">
            <div class="flex items-start justify-between gap-4"><div><h2 class="text-2xl font-semibold">Backups</h2><p class="mt-2 text-sm text-ink-400">Create and manage server backups to protect your data.</p></div><div class="flex gap-2"><button class="rounded-lg border border-bad/50 px-4 py-2 text-sm text-bad">Delete All Backups</button><button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950">New Backup</button></div></div>
            <div class="rounded-xl border border-ink-700 bg-ink-900 p-5 text-sm text-ink-300">☐ &nbsp; Select backups</div>
          </div>

          <div v-else-if="active === 'networking'" class="space-y-6">
            <div><h2 class="text-2xl font-semibold">Ports</h2><p class="mt-2 text-sm text-ink-400">Configure network settings, IP addresses and ports your server can bind to.</p></div>
            <div class="rounded-xl border border-ink-700 bg-ink-900 p-5"><div class="flex items-center justify-between"><h3 class="text-lg font-semibold">Port Allocations</h3><button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950">New Allocation</button></div><div class="mt-5 rounded-lg border border-ink-700 bg-ink-950 p-4"><p class="font-mono text-sm text-ink-200">◉ &nbsp; {{ server.allocations[0]?.ip }}:{{ server.allocations[0]?.port }} <span class="ml-2 rounded bg-accent-500/15 px-2 py-1 text-xs text-accent-300">Primary</span></p></div></div>
          </div>

          <div v-else-if="active === 'users'" class="space-y-6"><div class="flex items-start justify-between"><div><h2 class="text-2xl font-semibold">Access</h2><p class="mt-2 text-sm text-ink-400">Manage user access to your server and permissions.</p></div><button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950">New User</button></div><div class="flex min-h-[24rem] items-center justify-center rounded-xl border border-ink-700 bg-ink-900 text-center"><div><h3 class="text-lg font-semibold">No users found</h3><p class="mt-2 text-sm text-ink-400">No additional users have access to this server.</p></div></div></div>

          <StartupPanel v-else-if="active === 'startup'" :server-id="server.id" :status="server.status" />

          <div v-else-if="active === 'schedules'" class="space-y-6"><div class="flex items-start justify-between"><div><h2 class="text-2xl font-semibold">Automations</h2><p class="mt-2 text-sm text-ink-400">Automate server tasks with scheduled commands and backups.</p></div><button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950">New Schedule</button></div><div class="min-h-[20rem] rounded-xl border border-ink-700 bg-ink-900"></div></div>

          <div v-else-if="active === 'settings'" class="space-y-6"><div><h2 class="text-2xl font-semibold">Settings</h2><p class="mt-2 text-sm text-ink-400">Configure your server settings and maintenance actions.</p></div><div class="rounded-xl border border-ink-700 bg-ink-900 p-6"><h3 class="text-lg font-semibold">Server Details</h3><label class="mt-5 block text-sm text-ink-400">Server Name</label><input :value="server.name" class="mt-2 w-full rounded-lg border border-ink-700 bg-ink-950 px-4 py-3 text-sm text-ink-100" readonly /></div><div class="rounded-xl border border-ink-700 bg-ink-900 p-6"><h3 class="text-lg font-semibold">Reinstall Server</h3><p class="mt-2 text-sm text-ink-400">Reinstalling stops the server and runs its installation script again.</p><button class="mt-5 rounded-lg border border-bad/50 px-4 py-2 text-sm text-bad">Reinstall Server</button></div></div>

          <div v-else-if="active === 'activity'" class="space-y-6"><div><h2 class="text-2xl font-semibold">Timeline</h2><p class="mt-2 text-sm text-ink-400">Monitor server activity and track actions performed on this server.</p></div><div class="min-h-[24rem] rounded-xl border border-ink-700 bg-ink-900 p-6"><h3 class="text-lg font-semibold">Events</h3><p class="mt-10 text-center text-sm text-ink-500">No activity events found.</p></div></div>
        </template>
      </main>
    </div>
    <div v-else class="rounded-xl border border-ink-700 bg-ink-900 p-8 text-ink-400">{{ error || "Loading server…" }}</div>
  </AppLayout>
</template>
