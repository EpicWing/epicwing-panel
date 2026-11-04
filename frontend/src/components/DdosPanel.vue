<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "../api/client";

const props = defineProps<{
  serverId: string;
  online: boolean;
  rx: number[];
  tx: number[];
}>();

// Status of the detection in the backend, see GET /servers/{id}/ddos.
interface DdosStatus {
  online: boolean;
  level: string;
  reasons: string[];
  layers: string[];
  samples: number;
  rates: Record<string, number | null>;
  history: { step_seconds: number; rx: number[]; tx: number[] };
}

const POLL_MS = 3000;

const WIDTH = 300;
const HEIGHT = 72;
const POINTS = 360; // 60 min at 10 s steps
const RX_COLOR = "#49c58a";
const TX_COLOR = "#f778ba";

type Level = "loading" | "unavailable" | "offline" | "learning" | "normal" | "watch" | "attack";

const LEVELS: Record<Level, { label: string; hint: string; dot: string }> = {
  loading: { label: "Loading", hint: "Fetching the status.", dot: "bg-ink-500 text-ink-500" },
  unavailable: { label: "Status unavailable", hint: "The status could not be loaded. Trying again.", dot: "bg-ink-500 text-ink-500" },
  offline: { label: "Offline", hint: "The server is not running.", dot: "bg-ink-500 text-ink-500" },
  learning: { label: "Learning", hint: "Collecting traffic to learn what is normal for this server.", dot: "bg-ink-400 text-ink-400" },
  normal: { label: "Normal", hint: "Traffic and console activity are in the usual range.", dot: "bg-ok text-ok" },
  watch: { label: "Unusual", hint: "Traffic or console activity is clearly above the usual range.", dot: "bg-warn text-warn" },
  attack: { label: "Possible attack", hint: "Traffic or console activity is far above the usual range.", dot: "bg-bad text-bad animate-pulse" },
};

const RANGES = [
  { key: "1h", label: "1 h" },
  { key: "24h", label: "24 h" },
  { key: "7d", label: "7 days" },
  { key: "14d", label: "14 days" },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];
const range = ref<RangeKey>("1h");

const LAYERS: Record<string, string> = {
  network: "Network (IP)",
  transport: "Transport (TCP/UDP)",
  application: "Application (console)",
};

function setRange(key: RangeKey): void {
  range.value = key;
  void refresh();
}

const status = ref<DdosStatus | null>(null);
const failed = ref(false);
let timer: number | undefined;
let busy = false;
let disposed = false;

async function refresh(): Promise<void> {
  if (busy) return;
  busy = true;
  try {
    const result = await api<DdosStatus>(`/servers/${props.serverId}/ddos?range=${range.value}`);
    if (disposed) return;
    status.value = result;
    failed.value = false;
  } catch {
    if (!disposed) failed.value = true;
  } finally {
    busy = false;
  }
}

onMounted(() => {
  void refresh();
  timer = window.setInterval(() => void refresh(), POLL_MS);
});

onBeforeUnmount(() => {
  disposed = true;
  if (timer !== undefined) window.clearInterval(timer);
});

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

function count(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined) return "–";
  return `${Math.round(value).toLocaleString("en-US")} ${unit}`;
}

const level = computed<Level>(() => {
  if (!props.online) return "offline";
  if (failed.value) return "unavailable";
  if (!status.value) return "loading";
  const known = status.value.level;
  return known in LEVELS ? (known as Level) : "unavailable";
});

// Rates are only meaningful while the backend has fresh data.
const live = computed(() => props.online && !failed.value && status.value?.online === true);
const rates = computed(() => (live.value ? (status.value?.rates ?? {}) : {}));
const reasons = computed(() => (live.value ? (status.value?.reasons ?? []) : []));
const layers = computed(() => (live.value ? (status.value?.layers ?? []) : []));

const usual = computed(() => rates.value.usual_rx_bytes_per_s ?? null);
const factor = computed(() => {
  const now = rates.value.rx_bytes_per_s;
  if (usual.value === null || now === null || now === undefined) return null;
  return now / Math.max(usual.value, 1);
});

const chartRx = computed(() => status.value?.history.rx ?? []);
const chartTx = computed(() => status.value?.history.tx ?? []);

const latest = computed(() => props.rx[props.rx.length - 1] ?? rates.value.rx_bytes_per_s ?? 0);
const latestTx = computed(() => props.tx[props.tx.length - 1] ?? rates.value.tx_bytes_per_s ?? 0);
// Peak of the last 2 minutes = last 12 buckets
const peakIn = computed(() =>
  Math.max(...(range.value === "1h" ? chartRx.value : props.rx).slice(-12), latest.value, 0),
);
// Number of chart slots: 1 h is anchored to the right edge, longer ranges fill the width.
const slots = computed(() => (range.value === "1h" ? POINTS : Math.max(chartRx.value.length, 2)));
const peak = computed(() => Math.max(...chartRx.value, ...chartTx.value, 1024));

function axis(fraction: number): string {
  if (!props.online) return fraction === 0 ? "0 B/s" : "";
  return `${formatBytes(peak.value * fraction)}/s`;
}

function line(values: number[]): string {
  if (!props.online || values.length < 2) return `M0,${HEIGHT} L${WIDTH},${HEIGHT}`;
  return values
    .map((value, index) => {
      const x = WIDTH - (values.length - 1 - index) * (WIDTH / (slots.value - 1));
      const y = HEIGHT - (value / peak.value) * (HEIGHT - 8);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function area(values: number[]): string {
  if (!props.online || values.length < 2) return "";
  const first = WIDTH - (values.length - 1) * (WIDTH / (slots.value - 1));
  return `${line(values)} L${WIDTH},${HEIGHT} L${first.toFixed(1)},${HEIGHT} Z`;
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h2 class="flex items-center gap-3 text-2xl font-semibold">
        <svg viewBox="0 0 24 24" class="h-6 w-6 text-accent-400" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l8 3v6c0 5-3.4 8.4-8 9-4.6-.6-8-4-8-9V6l8-3z" /><path d="M9 12l2 2 4-4" /></svg>
        DDoS
      </h2>
      <p class="mt-2 text-sm text-ink-400">Live traffic, plus alerts for unusual traffic and console floods.</p>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <p class="text-xs uppercase text-ink-400">Status</p>
        <p class="mt-2 flex items-center gap-2 text-xl font-semibold">
          <span class="h-2.5 w-2.5 rounded-full shadow-[0_0_10px_currentColor]" :class="LEVELS[level].dot"></span>
          {{ LEVELS[level].label }}
        </p>
        <p class="mt-1 text-xs text-ink-400">{{ LEVELS[level].hint }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <p class="text-xs uppercase text-ink-400">Incoming now</p>
        <p class="mt-2 text-xl font-semibold">{{ online ? formatBytes(latest) + "/s" : "Offline" }}</p>
        <p class="mt-1 text-xs text-ink-400">Peak (2 min): {{ online ? formatBytes(peakIn) + "/s" : "–" }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <p class="text-xs uppercase text-ink-400">Outgoing now</p>
        <p class="mt-2 text-xl font-semibold">{{ online ? formatBytes(latestTx) + "/s" : "Offline" }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <p class="text-xs uppercase text-ink-400">Usual incoming</p>
        <p class="mt-2 text-xl font-semibold">{{ usual !== null ? formatBytes(usual) + "/s" : "–" }}</p>
        <p class="mt-1 text-xs text-ink-400">{{ factor !== null ? "Now: " + factor.toFixed(1) + "× usual" : "Still learning" }}</p>
      </div>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <p class="text-xs uppercase text-ink-400">Packets in</p>
        <p class="mt-2 text-xl font-semibold">{{ count(rates.rx_packets_per_s, "/s") }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <p class="text-xs uppercase text-ink-400">Dropped / rejected</p>
        <p class="mt-2 text-xl font-semibold">{{ count(rates.dropped_per_s, "/s") }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <p class="text-xs uppercase text-ink-400">Console lines</p>
        <p class="mt-2 text-xl font-semibold">{{ count(rates.console_lines_per_s, "/s") }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <p class="text-xs uppercase text-ink-400">Console sources</p>
        <p class="mt-2 text-xl font-semibold">{{ count(rates.console_sources_per_s, "/s") }}</p>
      </div>
    </div>

    <div v-if="reasons.length" class="rounded-xl border border-ink-700 bg-ink-900 p-4">
      <p class="text-xs uppercase tracking-wider text-ink-400">Why this status</p>
      <div v-if="layers.length" class="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <span class="text-ink-400">Affected layer:</span>
        <span v-for="layer in layers" :key="layer" class="rounded-full border border-ink-700 px-2 py-0.5">{{ LAYERS[layer] ?? layer }}</span>
      </div>
      <ul class="mt-2 list-disc space-y-1 pl-5 text-sm">
        <li v-for="reason in reasons" :key="reason">{{ reason }}</li>
      </ul>
    </div>

    <div class="rounded-xl border border-ink-700 bg-ink-900 p-4">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p class="text-xs uppercase tracking-wider text-ink-400">{{ range === "1h" ? "Live traffic" : "Traffic history" }}</p>
          <p v-if="range !== '1h'" class="mt-1 text-xs text-ink-500">Highest value per 5 minutes</p>
          <div class="mt-2 flex gap-1">
            <button
              v-for="option in RANGES"
              :key="option.key"
              type="button"
              class="rounded-md border px-2 py-0.5 text-xs"
              :class="range === option.key ? 'border-accent-400 text-accent-400' : 'border-ink-700 text-ink-400'"
              @click="setRange(option.key)"
            >{{ option.label }}</button>
          </div>
        </div>
        <div class="flex items-center gap-4 text-xs text-ink-400">
          <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full" :style="{ backgroundColor: RX_COLOR }"></span>↓ Incoming</span>
          <span class="flex items-center gap-1.5"><span class="h-2 w-2 rounded-full" :style="{ backgroundColor: TX_COLOR }"></span>↑ Outgoing</span>
        </div>
      </div>
      <div class="mt-3 flex gap-2">
        <div class="flex h-64 flex-col justify-between py-2 font-mono text-[10px] leading-none text-ink-500">
          <span>{{ axis(1) }}</span><span>{{ axis(0.5) }}</span><span>{{ axis(0) }}</span>
        </div>
        <svg viewBox="0 0 300 80" class="h-64 min-w-0 flex-1" preserveAspectRatio="none" aria-hidden="true">
          <path :d="area(chartRx)" :fill="RX_COLOR" fill-opacity="0.2" />
          <path :d="line(chartRx)" fill="none" :stroke="RX_COLOR" stroke-width="2" vector-effect="non-scaling-stroke" />
          <path :d="area(chartTx)" :fill="TX_COLOR" fill-opacity="0.2" />
          <path :d="line(chartTx)" fill="none" :stroke="TX_COLOR" stroke-width="2" vector-effect="non-scaling-stroke" />
        </svg>
      </div>
    </div>

    <p class="rounded-xl border border-ink-700 bg-ink-900 p-4 text-sm text-ink-400">
      Detection runs on the panel server and keeps watching while no page of this server is open.
      Traffic that your firewall or provider drops before it reaches the server is not counted here.
      Containers in host network mode share the packet counters of the node.
    </p>
  </div>
</template>
