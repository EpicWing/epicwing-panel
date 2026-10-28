<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import ServerConsole from "../components/ServerConsole.vue";
import { auth } from "../stores/auth";

interface AllocationRef {
  id: string;
  ip: string;
  port: number;
  is_primary: boolean;
}

interface ServerItem {
  id: string;
  name: string;
  owner_id: string;
  node_name: string;
  egg_name: string;
  status: string;
  last_error: string | null;
  allocations: AllocationRef[];
}

interface NodeItem {
  id: string;
  name: string;
}

interface EggVariable {
  env_variable: string;
  name: string;
  default_value: string;
  description: string;
  rules: string;
}

interface EggItem {
  id: string;
  name: string;
  nest_name: string;
  docker_image: string;
  startup: string;
  variables: EggVariable[];
}

interface AllocationItem {
  id: string;
  ip: string;
  port: number;
  server_id: string | null;
}

interface ServerForm {
  name: string;
  description: string;
  nodeId: string;
  eggId: string;
  allocationId: string;
  extraIds: string[];
  memoryMb: number;
  cpus: number;
  diskMb: number;
  image: string;
  startup: string;
  variables: Record<string, string>;
}

const { t, te } = useI18n();

function emptyForm(): ServerForm {
  return {
    name: "",
    description: "",
    nodeId: "",
    eggId: "",
    allocationId: "",
    extraIds: [],
    memoryMb: 1024,
    cpus: 1,
    diskMb: 5120,
    image: "",
    startup: "",
    variables: {},
  };
}

const servers = ref<ServerItem[]>([]);
const nodes = ref<NodeItem[]>([]);
const eggs = ref<EggItem[]>([]);
const free = ref<AllocationItem[]>([]);
const loading = ref(true);
const error = ref("");
const showForm = ref(false);
const busy = ref(false);
const form = ref<ServerForm>(emptyForm());
const consoleServer = ref<ServerItem | null>(null);

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const buttonClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100 disabled:opacity-40";
const primaryClass =
  "rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const dangerClass =
  "rounded-md border border-bad/50 px-3 py-1.5 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-40";

const dots: Record<string, string> = {
  new: "bg-ink-600",
  installing: "bg-warn",
  offline: "bg-ink-600",
  starting: "bg-warn",
  running: "bg-ok",
  stopping: "bg-warn",
  error: "bg-bad",
};

let timer: number | undefined;

const selectedEgg = computed(() => eggs.value.find((e) => e.id === form.value.eggId));
const extraOptions = computed(() =>
  free.value.filter((a) => a.id !== form.value.allocationId),
);
const extraPick = ref("");
const extraAvailable = computed(() =>
  extraOptions.value.filter((a) => !form.value.extraIds.includes(a.id)),
);
const extraChosen = computed(() =>
  extraOptions.value.filter((a) => form.value.extraIds.includes(a.id)),
);

function addExtra() {
  if (extraPick.value && !form.value.extraIds.includes(extraPick.value)) {
    form.value.extraIds.push(extraPick.value);
  }
  extraPick.value = "";
}

function removeExtra(id: string) {
  form.value.extraIds = form.value.extraIds.filter((x) => x !== id);
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

function isRequired(v: EggVariable): boolean {
  return v.rules.split("|").includes("required");
}

function isNumeric(v: EggVariable): boolean {
  const names = v.rules.split("|");
  return names.includes("integer") || names.includes("numeric");
}

function statusLabel(status: string): string {
  const key = `adminServers.status.${status}`;
  return te(key) ? t(key) : status;
}

function connection(server: ServerItem): string {
  const main = server.allocations.find((a) => a.is_primary) ?? server.allocations[0];
  if (!main) {
    return "–";
  }
  const extra = server.allocations.length - 1;
  return extra > 0 ? `${main.ip}:${main.port} (+${extra})` : `${main.ip}:${main.port}`;
}

function ownerLabel(server: ServerItem): string {
  return server.owner_id === auth.state.user?.id ? t("adminServers.you") : server.owner_id.slice(0, 8);
}

async function loadServers(first: boolean) {
  try {
    servers.value = await api<ServerItem[]>("/servers");
  } catch (e) {
    // A failed background refresh keeps the last data on screen.
    if (first) {
      error.value = message(e);
    }
  } finally {
    if (first) {
      loading.value = false;
    }
  }
}

function onEggChange() {
  const egg = selectedEgg.value;
  form.value.variables = Object.fromEntries(
    (egg?.variables ?? []).map((v) => [v.env_variable, v.default_value]),
  );
}

async function onNodeChange() {
  free.value = [];
  form.value.allocationId = "";
  form.value.extraIds = [];
  if (!form.value.nodeId) {
    return;
  }
  try {
    const rows = await api<AllocationItem[]>(`/nodes/${form.value.nodeId}/allocations`);
    free.value = rows.filter((r) => r.server_id === null);
    form.value.allocationId = free.value[0]?.id ?? "";
  } catch (e) {
    error.value = message(e);
  }
}

async function openForm() {
  error.value = "";
  try {
    const [nodeList, eggList] = await Promise.all([
      api<NodeItem[]>("/nodes"),
      api<EggItem[]>("/eggs"),
    ]);
    nodes.value = nodeList;
    eggs.value = eggList;
  } catch (e) {
    error.value = message(e);
    return;
  }
  form.value = emptyForm();
  form.value.nodeId = nodes.value[0]?.id ?? "";
  form.value.eggId = eggs.value[0]?.id ?? "";
  onEggChange();
  await onNodeChange();
  autoInstall.value = true;
  showForm.value = true;
}

const autoInstall = ref(true);

async function create() {
  const user = auth.state.user;
  if (!user) {
    return;
  }
  error.value = "";
  const f = form.value;
  const body: Record<string, unknown> = {
    name: f.name,
    description: f.description,
    owner_id: user.id,
    node_id: f.nodeId,
    egg_id: f.eggId,
    allocation_id: f.allocationId,
    extra_allocation_ids: f.extraIds.filter((id) => id !== f.allocationId),
    memory_mb: Number(f.memoryMb),
    cpus: Number(f.cpus),
    disk_mb: Number(f.diskMb),
    variables: f.variables,
  };
  if (f.image.trim()) {
    body.image = f.image.trim();
  }
  if (f.startup.trim()) {
    body.startup = f.startup.trim();
  }
  busy.value = true;
  try {
    const created = await api<ServerItem>("/servers", { method: "POST", body });
    showForm.value = false;
    await loadServers(false);
    if (autoInstall.value) {
      void act(created, "install");
    }
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function remove(server: ServerItem) {
  if (!window.confirm(t("adminServers.deleteConfirm", { name: server.name }))) {
    return;
  }
  error.value = "";
  try {
    await api<void>(`/servers/${server.id}`, { method: "DELETE" });
  } catch (e) {
    error.value = message(e);
  } finally {
    await loadServers(false);
  }
}

const working = ref("");

async function act(server: ServerItem, path: string, body?: Record<string, unknown>) {
  error.value = "";
  working.value = server.id;
  try {
    await api<ServerItem>(`/servers/${server.id}/${path}`, { method: "POST", body });
  } catch (e) {
    error.value = message(e);
  } finally {
    working.value = "";
    await loadServers(false);
  }
}

function install(server: ServerItem) {
  const ask = server.status !== "new";
  if (ask && !window.confirm(t("adminServers.reinstallConfirm", { name: server.name }))) {
    return;
  }
  void act(server, "install");
}

function power(server: ServerItem, action: "start" | "stop" | "kill") {
  if (action === "kill" && !window.confirm(t("adminServers.killConfirm", { name: server.name }))) {
    return;
  }
  void act(server, "power", { action });
}

function canInstall(server: ServerItem): boolean {
  return ["new", "offline", "error"].includes(server.status);
}

function canStart(server: ServerItem): boolean {
  return ["offline", "error"].includes(server.status);
}

function canStop(server: ServerItem): boolean {
  return ["running", "starting"].includes(server.status);
}

function canKill(server: ServerItem): boolean {
  return ["running", "starting", "stopping"].includes(server.status);
}

onMounted(() => {
  void loadServers(true);
  timer = window.setInterval(() => void loadServers(false), 5000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <AppLayout area="admin" wide :title="t('adminServers.title')" :subtitle="t('adminServers.subtitle')">
    <template #actions>
      <button
        v-if="!showForm"
        class="rounded-md bg-accent-500 px-3 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400"
        @click="openForm"
      >
        {{ t("adminServers.create") }}
      </button>
      <button v-else :class="buttonClass" @click="showForm = false">
        {{ t("adminServers.cancel") }}
      </button>
    </template>

    <p class="mb-6 rounded-lg border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-400">
      {{ t("adminServers.note") }}
    </p>

    <p
      v-if="error"
      role="alert"
      class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
    >
      {{ error }}
    </p>

    <form
      v-if="showForm"
      class="mb-6 grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5 sm:grid-cols-2"
      @submit.prevent="create"
    >
      <p
        v-if="nodes.length === 0 || eggs.length === 0"
        class="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn sm:col-span-2"
      >
        {{ t("adminServers.needSetup") }}
      </p>

      <div>
        <label for="s-name" class="mb-1.5 block text-sm text-ink-300">{{ t("adminServers.name") }}</label>
        <input id="s-name" v-model="form.name" required maxlength="64" :class="inputClass" />
      </div>
      <div>
        <label for="s-desc" class="mb-1.5 block text-sm text-ink-300">
          {{ t("adminServers.description") }}
        </label>
        <input id="s-desc" v-model="form.description" maxlength="255" :class="inputClass" />
      </div>
      <div>
        <label for="s-node" class="mb-1.5 block text-sm text-ink-300">{{ t("adminServers.node") }}</label>
        <select
          id="s-node"
          v-model="form.nodeId"
          required
          :class="inputClass"
          @change="onNodeChange"
        >
          <option v-for="n in nodes" :key="n.id" :value="n.id">{{ n.name }}</option>
        </select>
      </div>
      <div>
        <label for="s-egg" class="mb-1.5 block text-sm text-ink-300">{{ t("adminServers.egg") }}</label>
        <select id="s-egg" v-model="form.eggId" required :class="inputClass" @change="onEggChange">
          <option v-for="e in eggs" :key="e.id" :value="e.id">{{ e.nest_name }} / {{ e.name }}</option>
        </select>
      </div>
      <div>
        <label for="s-alloc" class="mb-1.5 block text-sm text-ink-300">
          {{ t("adminServers.allocation") }}
        </label>
        <select id="s-alloc" v-model="form.allocationId" required :class="inputClass">
          <option v-for="a in free" :key="a.id" :value="a.id">{{ a.ip }}:{{ a.port }}</option>
        </select>
        <p v-if="form.nodeId && free.length === 0" class="mt-1.5 text-xs text-bad">
          {{ t("adminServers.noAllocation") }}
        </p>
      </div>
      <div>
        <label class="mb-1.5 block text-sm text-ink-300">
          {{ t("adminServers.extraAllocations") }}
        </label>
        <select v-if="extraAvailable.length > 0" v-model="extraPick" :class="inputClass" @change="addExtra">
          <option value="">{{ t("adminServers.extraAdd") }}</option>
          <option v-for="a in extraAvailable" :key="a.id" :value="a.id">{{ a.ip }}:{{ a.port }}</option>
        </select>
        <div v-if="extraChosen.length > 0" class="mt-2 flex flex-wrap gap-2">
          <span
            v-for="a in extraChosen"
            :key="a.id"
            class="inline-flex items-center gap-1.5 rounded-md border border-ink-700 bg-ink-950 px-2.5 py-1 font-mono text-xs text-ink-100"
          >
            {{ a.ip }}:{{ a.port }}
            <button
              type="button"
              class="text-ink-400 hover:text-bad"
              :aria-label="t('adminServers.extraRemove')"
              @click="removeExtra(a.id)"
            >✕</button>
          </span>
        </div>
        <p class="mt-1.5 text-xs text-ink-400">{{ t("adminServers.extraHint") }}</p>
      </div>

      <div>
        <label for="s-mem" class="mb-1.5 block text-sm text-ink-300">{{ t("adminServers.memory") }}</label>
        <input
          id="s-mem"
          v-model.number="form.memoryMb"
          required
          type="number"
          min="0"
          max="65536"
          :class="inputClass"
        />
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label for="s-cpu" class="mb-1.5 block text-sm text-ink-300">{{ t("adminServers.cpus") }}</label>
          <input
            id="s-cpu"
            v-model.number="form.cpus"
            required
            type="number"
            step="0.1"
            min="0"
            max="64"
            :class="inputClass"
          />
        </div>
        <div>
          <label for="s-disk" class="mb-1.5 block text-sm text-ink-300">{{ t("adminServers.disk") }}</label>
          <input
            id="s-disk"
            v-model.number="form.diskMb"
            required
            type="number"
            min="0"
            :class="inputClass"
          />
        </div>
      </div>
      <p class="text-xs text-ink-400 sm:col-span-2">{{ t("adminServers.limitsHint") }}</p>

      <div v-if="selectedEgg && selectedEgg.variables.length > 0" class="sm:col-span-2">
        <p class="mb-2 text-sm text-ink-300">{{ t("adminServers.variables") }}</p>
        <div class="grid gap-4 sm:grid-cols-2">
          <div v-for="v in selectedEgg.variables" :key="v.env_variable">
            <label :for="`var-${v.env_variable}`" class="mb-1.5 block text-sm text-ink-300">
              {{ v.name }}
              <span class="ml-1 font-mono text-xs text-ink-400">{{ v.env_variable }}</span>
            </label>
            <input
              :id="`var-${v.env_variable}`"
              v-model="form.variables[v.env_variable]"
              maxlength="1024"
              :required="isRequired(v)"
              :inputmode="isNumeric(v) ? 'numeric' : undefined"
              :class="inputClass"
            />
            <p v-if="v.description" class="mt-1.5 text-xs text-ink-400">{{ v.description }}</p>
          </div>
        </div>
      </div>

      <details class="rounded-md border border-ink-700 bg-ink-950/40 px-4 py-3 sm:col-span-2">
        <summary class="cursor-pointer select-none text-sm text-ink-300">
          {{ t("adminServers.advanced") }}
        </summary>
        <div class="mt-3 grid gap-4 sm:grid-cols-2">
          <div>
            <label for="s-image" class="mb-1.5 block text-sm text-ink-300">
              {{ t("adminServers.image") }}
            </label>
            <input
              id="s-image"
              v-model="form.image"
              maxlength="255"
              :placeholder="selectedEgg?.docker_image"
              :class="inputClass"
            />
          </div>
          <div>
            <label for="s-startup" class="mb-1.5 block text-sm text-ink-300">
              {{ t("adminServers.startup") }}
            </label>
            <input
              id="s-startup"
              v-model="form.startup"
              maxlength="2048"
              :placeholder="selectedEgg?.startup"
              :class="[inputClass, 'font-mono']"
            />
          </div>
          <p class="text-xs text-ink-400 sm:col-span-2">{{ t("adminServers.overrideHint") }}</p>
        </div>
      </details>

      <label class="flex items-center gap-2 text-sm text-ink-300 sm:col-span-2">
        <input v-model="autoInstall" type="checkbox" class="h-4 w-4 accent-accent-500" />
        {{ t("adminServers.autoInstall") }}
      </label>

      <div class="sm:col-span-2">
        <button
          type="submit"
          :disabled="busy || !form.nodeId || !form.eggId || !form.allocationId"
          :class="primaryClass"
        >
          {{ busy ? t("adminServers.submitting") : t("adminServers.submit") }}
        </button>
      </div>
    </form>

    <div class="overflow-x-auto rounded-lg border border-ink-700">
      <table class="w-full text-left text-sm">
        <thead class="bg-ink-900 text-xs uppercase tracking-wider text-ink-400">
          <tr>
            <th class="px-4 py-3 font-medium">{{ t("adminServers.colName") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("adminServers.colId") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("adminServers.colOwner") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("adminServers.colNode") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("adminServers.colConnection") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("adminServers.colStatus") }}</th>
            <th class="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-ink-700">
          <tr v-if="loading">
            <td colspan="7" class="px-4 py-4"><div class="space-y-3" aria-busy="true"><div class="skeleton h-8"></div><div class="skeleton h-8"></div><div class="skeleton h-8"></div></div></td>
          </tr>
          <tr v-else-if="servers.length === 0">
            <td colspan="7" class="px-4 py-10 text-center">
              <p class="font-medium">{{ t("adminServers.emptyTitle") }}</p>
              <p class="mx-auto mt-1 max-w-md text-sm text-ink-400">{{ t("adminServers.emptyBody") }}</p>
            </td>
          </tr>
          <tr v-for="server in servers" :key="server.id" class="hover:bg-ink-900/60">
            <td class="px-4 py-3">
              <router-link :to="`/servers/${server.id}`" class="font-medium hover:text-accent-300">{{ server.name }}</router-link>
              <p class="text-xs text-ink-400">{{ server.egg_name }}</p>
            </td>
            <td class="px-4 py-3 font-mono text-xs text-ink-400">{{ server.id }}</td>
            <td class="px-4 py-3 text-ink-300">{{ ownerLabel(server) }}</td>
            <td class="px-4 py-3 text-ink-300">{{ server.node_name }}</td>
            <td class="px-4 py-3 font-mono text-xs text-ink-300">{{ connection(server) }}</td>
            <td class="px-4 py-3">
              <span class="inline-flex items-center gap-2 text-ink-300">
                <span class="h-2 w-2 rounded-full" :class="dots[server.status] ?? 'bg-ink-600'"></span>
                {{ statusLabel(server.status) }}
              </span>
              <p v-if="server.last_error" class="mt-1 max-w-xs truncate text-xs text-bad">
                {{ server.last_error }}
              </p>
            </td>
            <td class="px-4 py-3 text-right">
              <div class="flex flex-wrap justify-end gap-2">
                <button
                  v-if="server.status === 'running' || server.status === 'starting' || server.status === 'error'"
                  :class="buttonClass"
                  :disabled="working === server.id"
                  @click="consoleServer = server"
                >
                  {{ t("adminServers.console") }}
                </button>
                <button
                  v-if="canInstall(server)"
                  :class="buttonClass"
                  :disabled="working === server.id"
                  @click="install(server)"
                >
                  {{ server.status === "new" ? t("adminServers.install") : t("adminServers.reinstall") }}
                </button>
                <button
                  v-if="server.status === 'offline' || server.status === 'error'"
                  :class="buttonClass"
                  :disabled="working === server.id"
                  @click="power(server, 'start')"
                >
                  {{ t("adminServers.start") }}
                </button>
                <button
                  v-if="canStop(server)"
                  :class="buttonClass"
                  :disabled="working === server.id"
                  @click="power(server, 'stop')"
                >
                  {{ t("adminServers.stop") }}
                </button>
                <button
                  v-if="canKill(server)"
                  :class="dangerClass"
                  :disabled="working === server.id"
                  @click="power(server, 'kill')"
                >
                  {{ t("adminServers.kill") }}
                </button>
                <button :class="dangerClass" :disabled="working === server.id" @click="remove(server)">
                  {{ t("adminServers.delete") }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ServerConsole
      v-if="consoleServer"
      :server-id="consoleServer.id"
      :server-name="consoleServer.name"
      @close="consoleServer = null"
    />
  </AppLayout>
</template>
