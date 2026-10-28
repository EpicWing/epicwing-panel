<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import ConsoleOutput from "../components/ConsoleOutput.vue";
import AccessPanel from "../components/AccessPanel.vue";
import ActivityPanel from "../components/ActivityPanel.vue";
import FilesPanel from "../components/FilesPanel.vue";
import BackupsPanel from "../components/BackupsPanel.vue";
import DatabasesPanel from "../components/DatabasesPanel.vue";
import SchedulesPanel from "../components/SchedulesPanel.vue";
import DdosPanel from "../components/DdosPanel.vue";
import BackupLimitField from "../components/BackupLimitField.vue";
import PortsPanel from "../components/PortsPanel.vue";
import StartupPanel from "../components/StartupPanel.vue";
import { type ConsoleFrame, useServerConsole } from "../composables/useServerConsole";
import { auth } from "../stores/auth";

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
  backup_limit: number;
  image: string;
  startup_command: string;
  node_name: string;
  egg_name: string;
  allocations: Allocation[];
  permissions?: string[];
}

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const server = ref<ServerData | null>(null);
const permissions = ref<string[]>([]);
const active = ref("home");
const command = ref("");
const error = ref("");
// Raw node text for admins (the backend leaves it out for everyone else).
const errorTechnical = ref("");
const metrics = ref({ cpu: 0, ram: 0, disk: 0, rx: 0, tx: 0 });
const startedAt = ref<string | null>(null);
const nowTick = ref(Date.now());
const history = ref({ cpu: [] as number[], ram: [] as number[], disk: [] as number[], rx: [] as number[], tx: [] as number[] });
let previousNetwork: { rx: number; tx: number; at: number } | null = null;

const groups = [
  { title: "Overview", items: [["home", "Home"], ["activity", "Timeline"]] },
  { title: "Manage", items: [["files", "Files"], ["startup", "Launch"], ["networking", "Ports"], ["ddos", "DDoS"], ["schedules", "Automations"]] },
  { title: "Data", items: [["databases", "Databases"], ["backups", "Backups"]] },
  { title: "Admin", items: [["users", "Access"], ["settings", "Settings"]] },
] as const;

// Linien-Icons (24x24) für die Seitenleiste, ohne zusätzliche Bibliothek.
const NAV_ICONS: Record<string, string> = {
  home: "M3 11l9-8 9 8 M5 10v10h14V10 M10 20v-6h4v6",
  activity: "M22 12h-4l-3 9L9 3l-3 9H2",
  files: "M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9l-.8-1.2A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z",
  startup: "M5 3l14 9-14 9V3z",
  networking: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z M2 12h20 M12 2a15 15 0 0 1 0 20 M12 2a15 15 0 0 0 0 20",
  schedules: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z M12 6v6l4 2",
  ddos: "M12 3l8 3v6c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V6l8-3z M9 12l2 2 4-4",
  databases: "M3 6c0-1.7 4-3 9-3s9 1.3 9 3-4 3-9 3-9-1.3-9-3z M21 12c0 1.7-4 3-9 3s-9-1.3-9-3 M3 6v12c0 1.7 4 3 9 3s9-1.3 9-3V6",
  backups: "M21 8v13H3V8 M1 3h22v5H1z M10 12h4",
  users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M22 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75",
  settings: "M4 21v-7 M4 10V3 M12 21v-9 M12 8V3 M20 21v-5 M20 12V3 M1 14h6 M9 8h6 M17 16h6",
};

function navIcon(key: string): string {
  return NAV_ICONS[key] ?? "M12 12h.01";
}

function onAllocationsChanged(rows: Allocation[]): void {
  if (server.value) server.value.allocations = rows;
}

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : t("common.unreachable");
}

function technical(cause: unknown): string {
  return cause instanceof ApiError ? (cause.technical ?? "") : "";
}

// The message under the console: a fresh error first, then the stored reason of an error state.
function shownError(): string {
  return (
    error.value ||
    consoleError.value ||
    (server.value?.status === "error" ? (server.value.last_error ?? "") : "")
  );
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

// rx and tx share one scale (floor 1 KiB/s) so an idle connection stays flat.
function scalePeak(key: string, values: number[]): number {
  if (key === "ram" && server.value && server.value.memory_mb > 0) return Math.max(server.value.memory_mb * 1024 * 1024, ...values);
  if (key !== "rx" && key !== "tx") return Math.max(...values, 1);
  return Math.max(...history.value.rx, ...history.value.tx, 1024);
}

// A new run starts with empty charts: reset when the server goes from stopped to starting/running.
function setStatus(next: string): void {
  if (!server.value) return;
  const wasOnline = isOnline();
  server.value.status = next;
  if (!wasOnline && isOnline()) {
    history.value = { cpu: [], ram: [], disk: [], rx: [], tx: [] }; metrics.value = { cpu: 0, ram: 0, disk: 0, rx: 0, tx: 0 };
    startedAt.value = null;
  }
}

function uptimeText(): string {
  const iso = startedAt.value;
  if (!isOnline() || !iso) return "0h 0m 0s";
  const started = Date.parse(iso.replace(/(\.\d{3})\d+/, "$1"));
  if (Number.isNaN(started)) return "0h 0m 0s";
  const seconds = Math.max(0, Math.floor((nowTick.value - started) / 1000));
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m ${seconds % 60}s`;
}

function smoothPath(points: string, area = 0): string {
  const pts = points.split(" ").map((point) => point.split(",").map(Number));
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    const mid = (x0 + x1) / 2;
    d += ` C${mid},${y0} ${mid},${y1} ${x1},${y1}`;
  }
  return area ? `${d} L${pts[pts.length - 1][0]},72 L${pts[0][0]},72 Z` : d;
}

const nameDraft = ref<string | null>(null);
const sftp = ref<{ username: string; host: string | null; port: number; write: boolean } | null>(null);

watch(
  () => server.value?.id,
  async (id) => {
    sftp.value = null;
    if (!id) return;
    try {
      const all = await api<
        { server_id: string; username: string; host: string | null; port: number; write: boolean }[]
      >("/ssh-keys/connections");
      sftp.value = all.find((row) => row.server_id === id) ?? null;
    } catch {
      sftp.value = null;
    }
  },
  { immediate: true },
);
const savingName = ref(false);
const nameError = ref("");
const nameSaved = ref(false);

function nameChanged(): boolean {
  const draft = (nameDraft.value ?? "").trim();
  return nameDraft.value !== null && draft.length > 0 && draft !== server.value?.name;
}

async function saveName(): Promise<void> {
  if (!server.value || !nameChanged() || savingName.value) return;
  savingName.value = true;
  nameError.value = "";
  nameSaved.value = false;
  try {
    const updated = await api<{ name: string }>(`/servers/${server.value.id}`, {
      method: "PATCH",
      body: { name: (nameDraft.value ?? "").trim() },
    });
    if (server.value) server.value.name = updated.name;
    nameDraft.value = null;
    nameSaved.value = true;
  } catch (cause) {
    nameError.value = message(cause);
  } finally {
    savingName.value = false;
  }
}

const reinstalling = ref(false);
const reinstallError = ref("");
const reinstallTechnical = ref("");

function canReinstall(): boolean {
  return !reinstalling.value && ["new", "offline", "error"].includes(server.value?.status ?? "");
}

async function reinstall(): Promise<void> {
  if (!server.value || !canReinstall()) return;
  // A server that was never installed has nothing to overwrite, so no confirmation.
  const ok =
    server.value.status === "new" ||
    window.confirm(
      `Reinstall ${server.value.name}? The container is replaced and the installation script runs again. This can overwrite files.`,
    );
  if (!ok) return;
  reinstalling.value = true;
  reinstallError.value = "";
  reinstallTechnical.value = "";
  try {
    const updated = await api<{ status: string; last_error: string | null }>(
      `/servers/${server.value.id}/install`,
      { method: "POST" },
    );
    setStatus(updated.status);
    if (server.value) server.value.last_error = updated.last_error;
  } catch (cause) {
    reinstallError.value = message(cause);
    reinstallTechnical.value = technical(cause);
    // A failed install leaves the server in the error state.
    try {
      if (server.value) {
        const fresh = await api<ServerData>(`/servers/${server.value.id}`);
        setStatus(fresh.status);
        server.value.last_error = fresh.last_error;
      }
    } catch {
      // The old state stays on screen.
    }
  } finally {
    reinstalling.value = false;
  }
}

function isOnline(): boolean {
  return server.value?.status === "running" || server.value?.status === "starting";
}

// Axis labels follow the scaling of the line: top = peak, middle = half, bottom = 0.
function axisLabel(key: string, fraction: number): string {
  const values = history.value[key as keyof typeof history.value] ?? [];
  const max = isOnline() ? scalePeak(key, values) : key === "cpu" ? 1 : key === "ram" && (server.value?.memory_mb ?? 0) > 0 ? scalePeak(key, []) : 0;
  const value = max * fraction;
  if (key === "cpu") return `${value.toFixed(2)}%`;
  if (value > 0) return formatBytes(value);
  return fraction === 0 ? formatBytes(0) : "";
}

function chartPoints(key: string): string {
  const values = history.value[key as keyof typeof history.value] ?? [];
  if (!isOnline() || values.length < 2) return "0,72 300,72";
  const max = scalePeak(key, values);
  return values.map((value, index) => `${300 - (values.length - 1 - index) * (300 / 59)},${72 - (value / max) * 64}`).join(" ");
}

function networkAxisLabel(fraction: number): string {
  const peak = isOnline() ? Math.max(...history.value.rx, ...history.value.tx, 1024) : 0;
  const value = peak * fraction;
  if (value > 0) return formatBytes(value);
  return fraction === 0 ? formatBytes(0) : "";
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

// Neuer Messpunkt: die Linien gleiten um einen Schritt nach links.
const chartTick = ref(0);
watch(history, () => { chartTick.value++; }, { deep: true });

function handleFrame(frame: ConsoleFrame): void {
  if (frame.type === "stats") {
    const stats = frame as ConsoleFrame & {
      cpu_percent: number;
      memory_used_bytes: number;
      disk_used_bytes: number;
      network_rx_bytes: number;
      network_tx_bytes: number;
      started_at?: string;
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
    if (stats.started_at) startedAt.value = stats.started_at;
  }
  if (frame.type === "status" && frame.status && server.value) setStatus(frame.status);
}

const {
  lines,
  status: connection,
  error: consoleError,
  connect: connectConsole,
  clear: clearConsole,
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
    if (server.value && server.value.id === fresh.id) setStatus(fresh.status);
  } catch {
    // The next poll tries again.
  }
}

onMounted(() => {
  statusTimer = window.setInterval(() => void refreshStatus(), 3000);
});
let clockTimer: number | undefined;
onMounted(() => {
  clockTimer = window.setInterval(() => {
    nowTick.value = Date.now();
  }, 1000);
});
onBeforeUnmount(() => {
  window.clearInterval(statusTimer);
  window.clearInterval(clockTimer);
});

const powerBusy = ref<string | null>(null);

async function power(action: "start" | "restart" | "stop" | "kill"): Promise<void> {
  if (!server.value || powerBusy.value !== null) return;
  if (action === "restart") {
    history.value = { cpu: [], ram: [], disk: [], rx: [], tx: [] }; metrics.value = { cpu: 0, ram: 0, disk: 0, rx: 0, tx: 0 };
    startedAt.value = null;
  }
  if (action === "start") {
    clearConsole();
    startedAt.value = null;
    history.value = { cpu: [], ram: [], disk: [], rx: [], tx: [] }; metrics.value = { cpu: 0, ram: 0, disk: 0, rx: 0, tx: 0 };
  }
  powerBusy.value = action;
  error.value = "";
  errorTechnical.value = "";
  try {
    server.value = await api<ServerData>(`/servers/${server.value.id}/power`, {
      method: "POST",
      body: { action },
    });
  } catch (cause) {
    error.value = message(cause);
    errorTechnical.value = technical(cause);
    // The backend may have moved the server to the error state; show its real state.
    try {
      if (server.value) {
        const fresh = await api<ServerData>(`/servers/${server.value.id}`);
        setStatus(fresh.status);
        server.value.last_error = fresh.last_error;
      }
    } catch {
      // The old state stays on screen.
    }
  } finally {
    powerBusy.value = null;
  }
}

onMounted(async () => {
  try {
    server.value = await api<ServerData>(`/servers/${String(route.params.id)}`);
    permissions.value = server.value.permissions ?? [];
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
          class="mb-0.5 flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm font-medium transition last:mb-0"
          :class="active === item[0] ? 'bg-accent-500/15 text-accent-300' : 'text-ink-200 hover:bg-ink-800 hover:text-ink-100'"
          @click="active = item[0]"
        >
            <svg viewBox="0 0 24 24" class="h-[18px] w-[18px] shrink-0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="navIcon(item[0])" /></svg>
            <span>{{ item[1] }}</span>
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
        <button class="px-6 py-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40" :class="server?.status === 'running' || server?.status === 'starting' ? 'text-ink-300' : 'bg-accent-500 text-ink-950 hover:bg-accent-400'" :disabled="server?.status === 'running' || server?.status === 'starting' || server?.status === 'new' || server?.status === 'installing' || powerBusy !== null" :title="server?.status === 'new' ? 'This server has not been installed yet' : undefined" @click="power('start')"><span v-if="powerBusy === 'start'" class="spinner mr-2"></span>Start</button>
        <button class="border-l border-ink-700 px-6 py-3 text-sm font-semibold text-ink-100 transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-40" :disabled="(server?.status !== 'running' && server?.status !== 'starting') || powerBusy !== null" @click="power('restart')"><span v-if="powerBusy === 'restart'" class="spinner mr-2"></span>Restart</button>
        <button class="border-l px-6 py-3 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40" :class="server?.status === 'running' || server?.status === 'starting' ? 'border-accent-400/30 bg-accent-500 text-ink-950 hover:bg-accent-400' : 'border-ink-700 text-ink-300'" :disabled="(server?.status !== 'running' && server?.status !== 'starting') || powerBusy !== null" @click="power('stop')"><span v-if="powerBusy === 'stop'" class="spinner mr-2"></span>Stop</button>
      </div>
    </template>

    <div v-if="server">
      <main class="min-w-0 space-y-3">
        <div v-if="active === 'home'" class="flex flex-wrap items-center justify-start gap-3">
          <div>
            <span class="inline-flex items-center gap-2 rounded-full border border-ink-700 bg-ink-900 px-3 py-1.5 text-sm font-medium text-ink-200 shadow-sm">
              <span class="h-2 w-2 rounded-full" :class="server.status === 'running' ? 'bg-ok' : server.status === 'starting' ? 'bg-warn' : 'bg-bad'" />
              {{ server.status === 'running' ? 'Running' : server.status === 'starting' ? 'Starting' : server.status === 'error' ? 'Error' : server.status === 'new' ? 'Not installed' : server.status === 'installing' ? 'Installing' : 'Offline' }}
            </span>
          </div>
          <span class="inline-flex items-center rounded-full border border-ink-700 bg-ink-900 px-3 py-1.5 text-sm font-medium text-ink-200 shadow-sm">Uptime: {{ uptimeText() }}</span>
        </div>

        <div v-if="active === 'home'" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4"><p class="text-xs uppercase text-ink-400">IP address</p><p class="mt-2 truncate font-mono text-lg font-semibold">{{ server.allocations[0]?.ip }}:{{ server.allocations[0]?.port }}</p></div>
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4"><p class="text-xs uppercase text-ink-400">CPU usage</p><p class="mt-2 text-xl font-semibold">{{ server?.status === 'running' || server?.status === 'starting' ? metrics.cpu.toFixed(1) + '%' : 'Offline' }}</p></div>
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4"><p class="text-xs uppercase text-ink-400">RAM usage</p><p class="mt-2 text-xl font-semibold">{{ server?.status === 'running' || server?.status === 'starting' ? formatBytes(metrics.ram) : 'Offline' }}</p></div>
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4"><p class="text-xs uppercase text-ink-400">Storage usage</p><p class="mt-2 text-xl font-semibold">{{ formatBytes(metrics.disk) }}</p></div>
        </div>

        <p v-if="active === 'home' && server.status === 'new'" class="rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-ink-100">This server has not been installed yet. Open Settings and choose Install Server to set it up.</p>

        <section v-if="active === 'home'" class="overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
          <ConsoleOutput :lines="lines" :placeholder="t('console.waiting')" :offline-text="server.status === 'running' || server.status === 'starting' ? undefined : server.status === 'installing' ? 'EpicWing container: Installing server, this can take a few minutes...' : 'EpicWing container: Server marked as offline...'" class="h-[min(34vh,28rem)] min-h-[17rem]" />
          <p v-if="shownError()" class="border-t border-bad/30 bg-bad/10 px-4 py-2 text-xs text-bad">{{ shownError() }}</p>
          <details v-if="errorTechnical" class="border-t border-bad/30 bg-bad/10 px-4 py-2 text-xs text-bad"><summary class="cursor-pointer select-none">Technical details (visible to admins only)</summary><pre class="mt-2 whitespace-pre-wrap break-all font-mono">{{ errorTechnical }}</pre></details>
          <form class="flex gap-2 border-t border-ink-700 p-3" @submit.prevent="sendCommand">
            <input v-model="command" class="min-w-0 flex-1 rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-sm outline-none focus:border-accent-500" placeholder="Enter a command…" :disabled="connection !== 'connected' && connection !== 'running'" autocomplete="off" />
            <button class="rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50" :disabled="!command.trim() || (connection !== 'connected' && connection !== 'running')">Send</button>
          </form>
        </section>

        <section v-if="active === 'home'" class="grid gap-4 lg:grid-cols-3">
          <div v-for="chart in [
            { key: 'cpu', title: 'CPU', value: (server.status === 'running' || server.status === 'starting') ? `${metrics.cpu.toFixed(1)}%` : 'Offline', color: '#e5534b' },
            { key: 'ram', title: 'RAM', value: (server.status === 'running' || server.status === 'starting') ? formatBytes(metrics.ram) : 'Offline', color: '#d9a21b' },
          ]" :key="chart.key" class="rounded-xl border border-ink-700 bg-ink-900 p-4">
            <div class="flex items-center justify-between"><p class="flex items-center gap-2 text-xs uppercase tracking-wider text-ink-400"><span class="h-2 w-2 rounded-full" :style="{ backgroundColor: chart.color }"></span>{{ chart.title }}</p><p class="font-mono text-sm">{{ chart.value }}</p></div>
            <div class="mt-3 flex gap-2"><div class="flex h-32 flex-col justify-between py-2 font-mono text-[10px] leading-none text-ink-500"><span>{{ axisLabel(chart.key, 1) }}</span><span>{{ axisLabel(chart.key, 0.5) }}</span><span>{{ axisLabel(chart.key, 0) }}</span></div><svg viewBox="0 0 300 80" class="h-32 min-w-0 flex-1" preserveAspectRatio="none" aria-hidden="true"><g :key="chartTick" :class="{ 'chart-glide': chartTick > 0 }" style="--glide: 5.085px"><path :d="smoothPath(chartPoints(chart.key), 300)" :fill="chart.color" fill-opacity="0.2" /><path :d="smoothPath(chartPoints(chart.key))" fill="none" :stroke="chart.color" stroke-width="2" vector-effect="non-scaling-stroke" /></g></svg></div>
          </div>
          <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
            <div class="flex items-center justify-between"><p class="text-xs uppercase tracking-wider text-ink-400">Network activity</p><p class="font-mono text-sm">↓ {{ formatBytes(metrics.rx) }}/s · ↑ {{ formatBytes(metrics.tx) }}/s</p></div>
            <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-400">
              <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full" style="background-color: #49c58a"></span>↓ Download (incoming)</span>
              <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full" style="background-color: #f778ba"></span>↑ Upload (outgoing)</span>
              <span class="text-ink-500">Both lines share one scale.</span>
            </div>
            <div class="mt-3 flex gap-2"><div class="flex h-32 flex-col justify-between py-2 font-mono text-[10px] leading-none text-ink-500"><span>{{ networkAxisLabel(1) }}</span><span>{{ networkAxisLabel(0.5) }}</span><span>{{ networkAxisLabel(0) }}</span></div><div class="min-w-0 flex-1"><svg viewBox="0 0 900 80" class="h-32 w-full" preserveAspectRatio="none" aria-hidden="true">
              <g :key="chartTick" :class="{ 'chart-glide': chartTick > 0 }" style="--glide: 15.254px"><path :d="smoothPath(networkPoints('rx'), 900)" fill="#49c58a" fill-opacity="0.2" /><path :d="smoothPath(networkPoints('rx'))" fill="none" stroke="#49c58a" stroke-width="2" vector-effect="non-scaling-stroke" />
              <path :d="smoothPath(networkPoints('tx'), 900)" fill="#f778ba" fill-opacity="0.2" /><path :d="smoothPath(networkPoints('tx'))" fill="none" stroke="#f778ba" stroke-width="2" vector-effect="non-scaling-stroke" /></g>
            </svg></div></div>
          </div>
        </section>

        <div v-else :key="active" class="tab-in">
          <FilesPanel v-if="active === 'files'" :server-id="server.id" :status="server.status" />
          <DatabasesPanel v-else-if="active === 'databases'" :server-id="server.id" :permissions="permissions" />

          <BackupsPanel v-else-if="active === 'backups'" :server-id="server.id" :status="server.status" :permissions="permissions" />

          <div v-else-if="active === 'networking'" class="space-y-6">
            <div><h2 class="text-2xl font-semibold">Ports</h2><p class="mt-2 text-sm text-ink-400">Configure network settings, IP addresses and ports your server can bind to.</p></div>
            <PortsPanel :server-id="server.id" :permissions="permissions" @changed="onAllocationsChanged" />
          </div>

          <AccessPanel v-else-if="active === 'users'" :server-id="server.id" :permissions="permissions" />

          <StartupPanel v-else-if="active === 'startup'" :server-id="server.id" :status="server.status" />

          <SchedulesPanel v-else-if="active === 'schedules'" :server-id="server.id" :permissions="permissions" />

          <DdosPanel v-else-if="active === 'ddos'" :server-id="server.id" :online="isOnline()" :rx="history.rx" :tx="history.tx" />

          <div v-else-if="active === 'settings'" class="space-y-6"><div><h2 class="text-2xl font-semibold">Settings</h2><p class="mt-2 text-sm text-ink-400">Configure your server settings and maintenance actions.</p></div><div class="rounded-xl border border-ink-700 bg-ink-900 p-6"><h3 class="text-lg font-semibold">Server Details</h3><label class="mt-5 block text-sm text-ink-400">Server Name</label><div class="mt-2 flex gap-3"><input :value="nameDraft ?? server.name" @input="nameDraft = ($event.target as HTMLInputElement).value; nameSaved = false" @keydown.enter.prevent="saveName()" class="w-full rounded-lg border border-ink-700 bg-ink-950 px-4 py-3 text-sm text-ink-100" /><button class="shrink-0 rounded-lg bg-accent-500 px-5 py-2 text-sm font-medium text-ink-950 transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-40" :disabled="!nameChanged() || savingName" @click="saveName()">{{ savingName ? "Saving…" : "Save" }}</button></div><p v-if="nameError" class="mt-3 text-sm text-bad">{{ nameError }}</p><p v-else-if="nameSaved" class="mt-3 text-sm text-ink-400">Saved.</p></div><div class="rounded-xl border border-ink-700 bg-ink-900 p-6"><h3 class="text-lg font-semibold">{{ server.status === 'new' ? 'Install Server' : 'Reinstall Server' }}</h3><p class="mt-2 text-sm text-ink-400">{{ server.status === 'new' ? 'Creates the container and runs the installation script.' : 'Reinstalling replaces the container and runs the installation script again. This can overwrite files.' }}</p><button class="mt-5 rounded-lg border border-bad/50 px-4 py-2 text-sm text-bad transition hover:bg-bad/10 disabled:cursor-not-allowed disabled:opacity-40" :disabled="!canReinstall()" @click="reinstall()">{{ reinstalling ? (server.status === 'new' ? "Installing…" : "Reinstalling…") : server.status === 'new' ? "Install Server" : "Reinstall Server" }}</button><p v-if="!canReinstall() && !reinstalling" class="mt-3 text-xs text-ink-400">Stop the server before reinstalling.</p><p v-if="reinstallError" class="mt-3 text-sm text-bad">{{ reinstallError }}</p><details v-if="reinstallTechnical" class="mt-3 text-xs text-bad"><summary class="cursor-pointer select-none">Technical details (visible to admins only)</summary><pre class="mt-2 whitespace-pre-wrap break-all font-mono">{{ reinstallTechnical }}</pre></details></div><div v-if="sftp" class="rounded-xl border border-ink-700 bg-ink-900 p-6"><h3 class="text-lg font-semibold">SFTP</h3><p class="mt-2 text-sm text-ink-400">Open this server's files in any SFTP program with your SSH key. Add a key under <RouterLink to="/ssh-keys" class="underline hover:text-ink-100">SSH Keys</RouterLink>.<span v-if="!sftp.write"> Your access is read only.</span></p><code class="mt-4 block select-all break-all rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-xs">sftp -P {{ sftp.port }} {{ sftp.username }}@{{ sftp.host ?? "NODE-ADDRESS" }}</code></div><BackupLimitField v-if="auth.state.user?.is_admin" :server-id="server.id" :limit="server.backup_limit" @saved="server.backup_limit = $event" /></div>

          <div v-else-if="active === 'activity'" class="space-y-6"><div><h2 class="text-2xl font-semibold">Timeline</h2><p class="mt-2 text-sm text-ink-400">Monitor server activity and track actions performed on this server.</p></div><ActivityPanel :server-id="server.id" :permissions="permissions" /></div>
        </div>
      </main>
    </div>
    <div v-else-if="error" class="rounded-xl border border-ink-700 bg-ink-900 p-8 text-ink-400">{{ error }}</div>
    <div v-else class="space-y-3" aria-busy="true"><div class="skeleton h-12"></div><div class="skeleton h-24"></div><div class="skeleton h-72"></div></div>
  </AppLayout>
</template>
