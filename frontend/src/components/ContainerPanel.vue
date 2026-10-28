<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";

interface ContainerItem {
  id: string;
  node_id: string;
  node_name: string;
  name: string;
  docker_name: string;
  image: string;
  host_port: number;
  container_port: number;
  protocol: string;
  memory_mb: number;
  cpus: number;
  status: string;
  last_error: string | null;
}

interface NodeItem {
  id: string;
  name: string;
  status: string;
  port_range_start: number;
  port_range_end: number;
}

const { t } = useI18n();

const containers = ref<ContainerItem[]>([]);
const nodes = ref<NodeItem[]>([]);
const error = ref("");
const showForm = ref(false);
const creating = ref(false);
const busyId = ref("");
const form = ref({
  nodeId: "",
  name: "",
  image: "nginx:1.27-alpine",
  hostPort: 25000,
  containerPort: 80,
  protocol: "tcp",
  memoryMb: 256,
  cpus: 0.5,
});

const dots: Record<string, string> = {
  creating: "bg-warn",
  created: "bg-ink-600",
  running: "bg-ok",
  stopped: "bg-ink-600",
  error: "bg-bad",
};

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const buttonClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100 disabled:opacity-40";
const primaryClass =
  "rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const dangerClass =
  "rounded-md border border-bad/50 px-3 py-1.5 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-40";

let timer: number | undefined;

const onlineNodes = computed(() => nodes.value.filter((n) => n.status === "online"));

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

async function load(first: boolean) {
  try {
    containers.value = await api<ContainerItem[]>("/containers");
  } catch (e) {
    // A failed background refresh keeps the last data on screen.
    if (first) {
      error.value = message(e);
    }
  }
}

async function loadNodes() {
  try {
    nodes.value = await api<NodeItem[]>("/nodes");
  } catch {
    // Without nodes the form simply offers none.
  }
}

function onNodeChange() {
  const node = nodes.value.find((n) => n.id === form.value.nodeId);
  if (node) {
    form.value.hostPort = node.port_range_start;
  }
}

async function openForm() {
  error.value = "";
  await loadNodes();
  form.value.nodeId = onlineNodes.value[0]?.id ?? "";
  onNodeChange();
  showForm.value = true;
}

async function create() {
  error.value = "";
  creating.value = true;
  try {
    await api<ContainerItem>("/containers", {
      method: "POST",
      body: {
        node_id: form.value.nodeId,
        name: form.value.name,
        image: form.value.image,
        host_port: Number(form.value.hostPort),
        container_port: Number(form.value.containerPort),
        protocol: form.value.protocol,
        memory_mb: Number(form.value.memoryMb),
        cpus: Number(form.value.cpus),
      },
    });
    showForm.value = false;
    form.value.name = "";
  } catch (e) {
    error.value = message(e);
  } finally {
    creating.value = false;
    await load(false);
  }
}

async function act(c: ContainerItem, verb: "start" | "stop") {
  error.value = "";
  busyId.value = c.id;
  try {
    await api<ContainerItem>(`/containers/${c.id}/${verb}`, { method: "POST" });
  } catch (e) {
    error.value = message(e);
  } finally {
    busyId.value = "";
    await load(false);
  }
}

async function remove(c: ContainerItem, force: boolean) {
  const key = force ? "containers.forceConfirm" : "containers.deleteConfirm";
  if (!window.confirm(t(key, { name: c.name }))) {
    return;
  }
  error.value = "";
  busyId.value = c.id;
  try {
    await api<void>(`/containers/${c.id}${force ? "?force=true" : ""}`, { method: "DELETE" });
  } catch (e) {
    error.value = message(e);
  } finally {
    busyId.value = "";
    await load(false);
  }
}

onMounted(() => {
  void load(true);
  timer = window.setInterval(() => void load(false), 5000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <section class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold">{{ t("containers.title") }}</h2>
      <button v-if="!showForm" :class="primaryClass" @click="openForm">
        {{ t("containers.add") }}
      </button>
    </div>

    <p
      v-if="error"
      role="alert"
      class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
    >
      {{ error }}
    </p>

    <form
      v-if="showForm"
      class="grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5 sm:grid-cols-2"
      @submit.prevent="create"
    >
      <div>
        <label for="c-node" class="mb-1.5 block text-sm text-ink-300">{{ t("containers.node") }}</label>
        <select
          id="c-node"
          v-model="form.nodeId"
          required
          :class="inputClass"
          @change="onNodeChange"
        >
          <option v-for="n in onlineNodes" :key="n.id" :value="n.id">{{ n.name }}</option>
        </select>
        <p v-if="onlineNodes.length === 0" class="mt-1.5 text-xs text-bad">
          {{ t("containers.noNode") }}
        </p>
      </div>
      <div>
        <label for="c-name" class="mb-1.5 block text-sm text-ink-300">{{ t("containers.name") }}</label>
        <input id="c-name" v-model="form.name" required maxlength="64" :class="inputClass" />
      </div>
      <div class="sm:col-span-2">
        <label for="c-image" class="mb-1.5 block text-sm text-ink-300">{{ t("containers.image") }}</label>
        <input id="c-image" v-model="form.image" required maxlength="255" :class="inputClass" />
        <p class="mt-1.5 text-xs text-ink-400">{{ t("containers.imageHint") }}</p>
      </div>
      <div>
        <label for="c-host" class="mb-1.5 block text-sm text-ink-300">{{ t("containers.hostPort") }}</label>
        <input
          id="c-host"
          v-model.number="form.hostPort"
          required
          type="number"
          min="1024"
          max="65535"
          :class="inputClass"
        />
      </div>
      <div>
        <label for="c-port" class="mb-1.5 block text-sm text-ink-300">
          {{ t("containers.containerPort") }}
        </label>
        <input
          id="c-port"
          v-model.number="form.containerPort"
          required
          type="number"
          min="1"
          max="65535"
          :class="inputClass"
        />
      </div>
      <div>
        <label for="c-proto" class="mb-1.5 block text-sm text-ink-300">{{ t("containers.protocol") }}</label>
        <select id="c-proto" v-model="form.protocol" :class="inputClass">
          <option value="tcp">tcp</option>
          <option value="udp">udp</option>
        </select>
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label for="c-mem" class="mb-1.5 block text-sm text-ink-300">{{ t("containers.memory") }}</label>
          <input
            id="c-mem"
            v-model.number="form.memoryMb"
            required
            type="number"
            min="16"
            max="65536"
            :class="inputClass"
          />
        </div>
        <div>
          <label for="c-cpu" class="mb-1.5 block text-sm text-ink-300">{{ t("containers.cpus") }}</label>
          <input
            id="c-cpu"
            v-model.number="form.cpus"
            required
            type="number"
            step="0.1"
            min="0.1"
            max="64"
            :class="inputClass"
          />
        </div>
      </div>
      <div class="flex gap-2 sm:col-span-2">
        <button type="submit" :disabled="creating || !form.nodeId" :class="primaryClass">
          {{ creating ? t("containers.creating") : t("containers.create") }}
        </button>
        <button type="button" :disabled="creating" :class="buttonClass" @click="showForm = false">
          {{ t("containers.cancel") }}
        </button>
      </div>
    </form>

    <div
      v-if="containers.length === 0 && !showForm"
      class="rounded-lg border border-dashed border-ink-700 px-6 py-14 text-center text-sm text-ink-400"
    >
      {{ t("containers.empty") }}
    </div>

    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <div
        v-for="c in containers"
        :key="c.id"
        class="relative overflow-hidden rounded-xl border border-ink-700 bg-ink-800 p-5 pl-6"
      >
        <span class="absolute inset-y-0 left-0 w-1" :class="dots[c.status] ?? 'bg-ink-600'"></span>
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h3 class="truncate text-lg font-semibold">{{ c.name }}</h3>
            <p class="truncate text-xs text-ink-400">{{ t("containers.onNode", { node: c.node_name }) }}</p>
          </div>
          <span
            class="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-ink-950 px-2.5 py-1 text-xs text-ink-300"
          >
            <span class="h-2 w-2 rounded-full" :class="dots[c.status] ?? 'bg-ink-600'"></span>
            {{ t(`containers.status.${c.status}`) }}
          </span>
        </div>
        <p class="mt-3 truncate rounded-md bg-ink-950 px-3 py-1.5 font-mono text-sm text-ink-300">
          :{{ c.host_port }} → {{ c.container_port }}/{{ c.protocol }}
        </p>
        <p class="mt-2 truncate font-mono text-xs text-ink-400" :title="c.image">{{ c.image }}</p>
        <p class="mt-1 font-mono text-xs text-ink-400">{{ c.memory_mb }} MB · {{ c.cpus }} CPU</p>
        <p v-if="c.last_error" class="mt-2 text-xs text-bad">{{ c.last_error }}</p>
        <div class="mt-4 flex flex-wrap gap-2">
          <button
            :class="buttonClass"
            :disabled="busyId === c.id || c.status === 'running' || c.status === 'creating'"
            @click="act(c, 'start')"
          >
            {{ t("containers.start") }}
          </button>
          <button
            :class="buttonClass"
            :disabled="busyId === c.id || c.status !== 'running'"
            @click="act(c, 'stop')"
          >
            {{ t("containers.stop") }}
          </button>
          <button
            :class="dangerClass"
            :disabled="busyId === c.id || c.status === 'creating'"
            @click="remove(c, false)"
          >
            {{ t("containers.delete") }}
          </button>
          <button
            v-if="c.status === 'error'"
            :class="dangerClass"
            :disabled="busyId === c.id"
            @click="remove(c, true)"
          >
            {{ t("containers.removeEntry") }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
