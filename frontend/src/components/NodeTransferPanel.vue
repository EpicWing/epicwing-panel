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

const STEPS = ["prepare", "backup", "upload", "download", "restore", "finish"];
const STEP_TEXT: Record<string, string> = {
  prepare: "Creating the container on the new node",
  backup: "Packing the files",
  upload: "Copying the files to the panel",
  download: "Copying the files to the new node",
  restore: "Unpacking the files",
  finish: "Switching over",
};

const targets = ref<Target[]>([]);
const state = ref<State | null>(null);
const nodeId = ref("");
const allocationId = ref("");
const dropBackups = ref(false);
const busy = ref(false);
const error = ref("");
let timer: number | undefined;

const base = computed(() => `/servers/${props.serverId}/node-transfer`);
const node = computed(() => targets.value.find((t) => t.id === nodeId.value));
const stopped = computed(() => props.status === "offline" || props.status === "error");
const localBackups = computed(() => state.value?.local_only_backups ?? 0);
const stepNumber = computed(() => STEPS.indexOf(state.value?.step ?? "") + 1);
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
      // Load the page again so the header shows the new node and status.
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
  <div class="max-w-2xl rounded-xl border border-ink-700 bg-ink-900 p-6">
    <template v-if="state?.running">
      <p class="text-sm text-ink-400">Step {{ stepNumber }} of {{ STEPS.length }}</p>
      <p class="mt-1 font-medium">{{ STEP_TEXT[state.step ?? ""] ?? "Working" }}…</p>
      <div class="mt-4 h-1.5 overflow-hidden rounded-full bg-ink-800">
        <div class="h-full rounded-full bg-accent-500 transition-all duration-500" :class="{ 'animate-pulse': state.progress === null }" :style="{ width: `${state.progress ?? (stepNumber / STEPS.length) * 100}%` }" />
      </div>
      <p class="mt-3 text-xs text-ink-400">
        <span v-if="state.progress !== null">{{ state.progress }}% of {{ size(state.size) }}. </span>You can leave this page, the move keeps running.
      </p>
    </template>

    <template v-else>
      <p v-if="state?.step === 'done'" class="mb-5 rounded-lg border border-ok/40 px-4 py-3 text-sm text-ok">The server was moved.</p>
      <p v-else-if="state?.step === 'failed'" class="mb-5 rounded-lg border border-bad/40 px-4 py-3 text-sm text-bad">
        Moving failed: {{ state.error }}<br /><span class="text-ink-400">Nothing was changed, the server is still on its old node.</span>
      </p>

      <p v-if="!targets.length" class="text-sm text-ink-400">There is no other node to move to.</p>
      <template v-else>
        <label class="block text-sm text-ink-400" for="transfer-node">Node</label>
        <select id="transfer-node" v-model="nodeId" class="mt-2 w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2.5 text-sm text-ink-100" @change="pickNode()">
          <option value="" disabled>Choose a node</option>
          <option v-for="t in targets" :key="t.id" :value="t.id">{{ t.name }}{{ t.status !== "online" ? ` (${t.status})` : "" }}</option>
        </select>

        <label class="mt-4 block text-sm text-ink-400" for="transfer-port">Port</label>
        <select id="transfer-port" v-model="allocationId" :disabled="!node" class="mt-2 w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2.5 text-sm text-ink-100 disabled:opacity-40">
          <option v-if="node && !node.allocations.length" value="" disabled>No free port on this node</option>
          <option v-for="a in node?.allocations ?? []" :key="a.id" :value="a.id">{{ a.ip }}:{{ a.port }}</option>
        </select>

        <label v-if="localBackups" class="mt-4 flex items-start gap-3 text-sm text-ink-300">
          <input v-model="dropBackups" type="checkbox" class="mt-1" />
          <span>Delete {{ localBackups }} backup{{ localBackups === 1 ? "" : "s" }} that only exist on the old node. Download them first if you still need them.</span>
        </label>

        <div class="mt-6 flex items-center gap-4">
          <button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-40" :disabled="!canStart" @click="start()">
            {{ busy ? "Starting…" : "Move server" }}
          </button>
          <span v-if="!stopped" class="text-xs text-ink-400">Stop the server first.</span>
        </div>
      </template>
    </template>

    <p v-if="error" class="mt-4 text-sm text-bad">{{ error }}</p>
  </div>
</template>
