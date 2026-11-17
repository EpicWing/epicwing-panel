<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";

interface Port {
  id: string;
  ip: string;
  port: number;
}

interface Target {
  id: string;
  name: string;
  status: string;
  allocations: Port[];
}

interface State {
  step: string | null;
  error: string | null;
  progress: number | null;
  size: number | null;
  running: boolean;
  local_only_backups?: number;
}

const props = defineProps<{ serverId: string; status: string }>();
const emit = defineEmits<{ started: []; finished: [] }>();

const targets = ref<Target[]>([]);
const state = ref<State | null>(null);
const nodeId = ref("");
const allocationId = ref("");
const dropBackups = ref(false);
const busy = ref(false);
const error = ref("");
let timer: number | undefined;

const STEPS: [string, string][] = [
  ["prepare", "Create the container on the new node"],
  ["backup", "Pack the files on the old node"],
  ["upload", "Send the archive to the panel"],
  ["download", "Download on the new node"],
  ["restore", "Unpack on the new node"],
  ["finish", "Switch over"],
];

function stepState(key: string): "done" | "active" | "open" {
  const current = STEPS.findIndex(([k]) => k === state.value?.step);
  const index = STEPS.findIndex(([k]) => k === key);
  if (index < current) return "done";
  return index === current ? "active" : "open";
}

const base = computed(() => `/servers/${props.serverId}/node-transfer`);
const node = computed(() => targets.value.find((t) => t.id === nodeId.value));
const stopped = computed(() => props.status === "offline" || props.status === "error");
const localBackups = computed(() => state.value?.local_only_backups ?? 0);
const canStart = computed(
  () =>
    stopped.value &&
    !!allocationId.value &&
    !busy.value &&
    !state.value?.running &&
    (localBackups.value === 0 || dropBackups.value),
);

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "The panel is not reachable.";
}

function size(bytes: number | null): string {
  if (!bytes) return "";
  return bytes >= 2 ** 30 ? `${(bytes / 2 ** 30).toFixed(1)} GiB` : `${Math.ceil(bytes / 2 ** 20)} MiB`;
}

async function poll(): Promise<void> {
  try {
    const wasRunning = state.value?.running;
    state.value = await api<State>(base.value);
    if (state.value.running) {
      timer = window.setTimeout(poll, 1500);
    } else if (wasRunning) {
      // Done or failed: the page loads the server again with its new node and status.
      emit("finished");
    }
  } catch (cause) {
    error.value = message(cause);
  }
}

async function start(): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    state.value = await api<State>(base.value, {
      method: "POST",
      body: { node_id: nodeId.value, allocation_id: allocationId.value, delete_local_backups: dropBackups.value },
    });
    emit("started");
    timer = window.setTimeout(poll, 1000);
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

function pickNode(): void {
  allocationId.value = node.value?.allocations[0]?.id ?? "";
}

onMounted(async () => {
  try {
    targets.value = await api<Target[]>(`${base.value}/targets`);
  } catch (cause) {
    error.value = message(cause);
  }
  await poll();
});

onBeforeUnmount(() => window.clearTimeout(timer));
</script>

<template>
  <div class="rounded-xl border border-ink-700 bg-ink-900 p-6">
    <h3 class="text-lg font-semibold">Move to another node</h3>
    <p class="mt-2 text-sm text-ink-400">
      Copies all files to another node and gives the server a port there. Additional ports are not taken along. The files on
      the old node stay as a safety copy until you delete them.
    </p>

    <div v-if="state?.running" class="mt-5">
      <ol class="space-y-2 text-sm">
        <li v-for="[key, label] in STEPS" :key="key" class="flex items-center gap-3" :class="stepState(key) === 'open' ? 'text-ink-500' : 'text-ink-100'">
          <span class="flex h-5 w-5 shrink-0 items-center justify-center">
            <span v-if="stepState(key) === 'active'" class="spinner text-accent-500" />
            <span v-else-if="stepState(key) === 'done'" class="text-ok">✓</span>
            <span v-else class="h-1.5 w-1.5 rounded-full bg-ink-600" />
          </span>
          <span>{{ label }}</span>
          <span v-if="stepState(key) === 'active' && state.progress !== null" class="ml-auto text-ink-400">{{ state.progress }}%</span>
          <span v-else-if="key === 'backup' && state.size" class="ml-auto text-ink-400">{{ size(state.size) }}</span>
        </li>
      </ol>
      <div class="mt-4 h-1.5 overflow-hidden rounded-full bg-ink-800">
        <div v-if="state.progress !== null" class="h-full rounded-full bg-accent-500 transition-all duration-500" :style="{ width: `${state.progress}%` }" />
        <div v-else class="transfer-indeterminate h-full w-1/3 rounded-full bg-accent-500" />
      </div>
      <p class="mt-3 text-xs text-ink-400">You can leave this page, the transfer keeps running.</p>
    </div>

    <template v-else>
      <p v-if="state?.step === 'done'" class="mt-4 text-sm text-ok">The server now runs on the new node.</p>
      <p v-else-if="state?.step === 'failed'" class="mt-4 text-sm text-bad">
        The transfer failed: {{ state.error }} The server stays on its current node.
      </p>

      <p v-if="!targets.length" class="mt-5 text-sm text-ink-400">There is no other node.</p>
      <div v-else class="mt-5 grid gap-4 sm:grid-cols-2">
        <label class="block text-sm text-ink-400">
          Node
          <select v-model="nodeId" class="mt-2 w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2.5 text-sm text-ink-100" @change="pickNode()">
            <option value="" disabled>Choose a node</option>
            <option v-for="t in targets" :key="t.id" :value="t.id">{{ t.name }}{{ t.status !== "online" ? ` (${t.status})` : "" }}</option>
          </select>
        </label>
        <label class="block text-sm text-ink-400">
          Port on the new node
          <select v-model="allocationId" :disabled="!node" class="mt-2 w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2.5 text-sm text-ink-100 disabled:opacity-40">
            <option v-if="node && !node.allocations.length" value="" disabled>No free port</option>
            <option v-for="a in node?.allocations ?? []" :key="a.id" :value="a.id">{{ a.ip }}:{{ a.port }}</option>
          </select>
        </label>
      </div>

      <label v-if="localBackups" class="mt-4 flex items-start gap-3 text-sm text-ink-300">
        <input v-model="dropBackups" type="checkbox" class="mt-1" />
        <span>{{ localBackups }} backup{{ localBackups === 1 ? "" : "s" }} only exist on the old node and will be removed. Download them first if you need them.</span>
      </label>

      <button
        class="mt-5 rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-40"
        :disabled="!canStart"
        @click="start()"
      >
        <span v-if="busy" class="spinner mr-2" />Move server
      </button>
      <p v-if="!stopped" class="mt-3 text-xs text-ink-400">Stop the server before moving it.</p>
    </template>

    <p v-if="error" class="mt-3 text-sm text-bad">{{ error }}</p>
  </div>
</template>

<style scoped>
.transfer-indeterminate {
  animation: transfer-slide 1.2s ease-in-out infinite;
}

@keyframes transfer-slide {
  from {
    transform: translateX(-100%);
  }
  to {
    transform: translateX(300%);
  }
}
</style>
