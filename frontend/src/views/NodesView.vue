<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

interface NodeItem {
  id: string;
  name: string;
  location: string;
  fqdn: string | null;
  status: string;
  cpu_total: number | null;
  ram_total_mb: number | null;
  disk_total_mb: number | null;
  port_range_start: number;
  port_range_end: number;
}

interface Enrollment {
  token: string;
  expires_at: string;
}

interface NodeForm {
  name: string;
  location: string;
  fqdn: string;
  portStart: number | "";
  portEnd: number | "";
}

const { t, te } = useI18n();

const emptyForm = (): NodeForm => ({ name: "", location: "", fqdn: "", portStart: "", portEnd: "" });

const nodes = ref<NodeItem[]>([]);
const loading = ref(true);
const error = ref("");
const showForm = ref(false);
const busy = ref(false);
const form = ref<NodeForm>(emptyForm());
const issued = ref<{ nodeName: string; enrollment: Enrollment } | null>(null);
const copied = ref(false);

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const buttonClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100";

const dots: Record<string, string> = {
  pending: "bg-warn",
  online: "bg-ok",
  offline: "bg-bad",
};

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

function statusLabel(status: string): string {
  const key = `nodes.status.${status}`;
  return te(key) ? t(key) : status;
}

function resources(node: NodeItem): string {
  if (node.cpu_total === null || node.ram_total_mb === null) {
    return "–";
  }
  return t("nodes.resourcesValue", {
    cpu: node.cpu_total,
    ram: Math.round(node.ram_total_mb / 1024),
  });
}

function toggleForm() {
  error.value = "";
  showForm.value = !showForm.value;
}

async function load() {
  try {
    nodes.value = await api<NodeItem[]>("/nodes");
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}

async function create() {
  error.value = "";
  const start = form.value.portStart;
  const end = form.value.portEnd;
  if ((start === "") !== (end === "")) {
    error.value = t("nodes.portsBoth");
    return;
  }

  const body: Record<string, unknown> = {
    name: form.value.name,
    location: form.value.location,
    fqdn: form.value.fqdn.trim() || null,
  };
  if (start !== "" && end !== "") {
    body.port_range_start = start;
    body.port_range_end = end;
  }

  busy.value = true;
  try {
    const result = await api<{ node: NodeItem; enrollment: Enrollment }>("/nodes", {
      method: "POST",
      body,
    });
    nodes.value.push(result.node);
    issued.value = { nodeName: result.node.name, enrollment: result.enrollment };
    copied.value = false;
    showForm.value = false;
    form.value = emptyForm();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function newToken(node: NodeItem) {
  error.value = "";
  try {
    const enrollment = await api<Enrollment>(`/nodes/${node.id}/enrollment`, { method: "POST" });
    issued.value = { nodeName: node.name, enrollment };
    copied.value = false;
  } catch (e) {
    error.value = message(e);
  }
}

async function copyToken() {
  if (!issued.value) {
    return;
  }
  try {
    await navigator.clipboard.writeText(issued.value.enrollment.token);
    copied.value = true;
  } catch {
    error.value = t("nodes.copyFailed");
  }
}

let timer: number | undefined;

// Background refresh: a failed request keeps the list on screen.
async function refresh() {
  try {
    nodes.value = await api<NodeItem[]>("/nodes");
  } catch {
    // The next tick tries again.
  }
}

onMounted(() => {
  void load();
  timer = window.setInterval(() => void refresh(), 5000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <AppLayout area="admin" :title="t('nodes.title')" :subtitle="t('nodes.subtitle')">
    <template #actions>
      <button
        class="rounded-md bg-accent-500 px-3 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400"
        @click="toggleForm"
      >
        {{ showForm ? t("nodes.cancel") : t("nodes.add") }}
      </button>
    </template>

    <p
      v-if="error"
      role="alert"
      class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
    >
      {{ error }}
    </p>

    <div
      v-if="issued"
      class="mb-6 rounded-lg border border-accent-500/40 bg-accent-500/5 p-4 text-sm"
    >
      <p class="font-medium">{{ t("nodes.tokenTitle", { name: issued.nodeName }) }}</p>
      <p class="mt-1 text-ink-300">
        {{ t("nodes.tokenBody", { date: formatDate(issued.enrollment.expires_at) }) }}
      </p>
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <code
          class="min-w-0 flex-1 break-all rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-xs"
        >
          {{ issued.enrollment.token }}
        </code>
        <button :class="buttonClass" @click="copyToken">
          {{ copied ? t("nodes.copied") : t("nodes.copy") }}
        </button>
        <button :class="buttonClass" @click="issued = null">{{ t("nodes.close") }}</button>
      </div>
    </div>

    <form
      v-if="showForm"
      class="mb-6 grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5 sm:grid-cols-2"
      @submit.prevent="create"
    >
      <div class="sm:col-span-2">
        <label for="name" class="mb-1.5 block text-sm text-ink-300">{{ t("nodes.name") }}</label>
        <input id="name" v-model="form.name" required maxlength="64" :class="inputClass" />
      </div>
      <div>
        <label for="fqdn" class="mb-1.5 block text-sm text-ink-300">{{ t("nodes.address") }}</label>
        <input
          id="fqdn"
          v-model="form.fqdn"
          :placeholder="t('nodes.addressPlaceholder')"
          :class="inputClass"
        />
        <p class="mt-1.5 text-xs text-ink-400">{{ t("nodes.addressHint") }}</p>
      </div>
      <div>
        <label for="location" class="mb-1.5 block text-sm text-ink-300">
          {{ t("nodes.location") }}
        </label>
        <input
          id="location"
          v-model="form.location"
          maxlength="64"
          :placeholder="t('nodes.locationPlaceholder')"
          :class="inputClass"
        />
      </div>

      <p class="text-xs text-ink-400 sm:col-span-2">{{ t("nodes.formHint") }}</p>
      <div class="sm:col-span-2">
        <button
          type="submit"
          :disabled="busy"
          class="rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60"
        >
          {{ busy ? t("nodes.creating") : t("nodes.create") }}
        </button>
      </div>
    </form>

    <div class="overflow-x-auto rounded-lg border border-ink-700">
      <table class="w-full text-left text-sm">
        <thead class="bg-ink-900 text-xs uppercase tracking-wider text-ink-400">
          <tr>
            <th class="px-4 py-3 font-medium">{{ t("nodes.colName") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("nodes.colLocation") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("nodes.colStatus") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("nodes.colPorts") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("nodes.colResources") }}</th>
            <th class="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-ink-700">
          <tr v-if="loading">
            <td colspan="6" class="px-4 py-4"><div class="space-y-3" aria-busy="true"><div class="skeleton h-8"></div><div class="skeleton h-8"></div><div class="skeleton h-8"></div></div></td>
          </tr>
          <tr v-else-if="nodes.length === 0">
            <td colspan="6" class="px-4 py-10 text-center">
              <p class="font-medium">{{ t("nodes.emptyTitle") }}</p>
              <p class="mx-auto mt-1 max-w-md text-sm text-ink-400">{{ t("nodes.helpBody") }}</p>
            </td>
          </tr>
          <tr v-for="node in nodes" :key="node.id" class="hover:bg-ink-900/60">
            <td class="px-4 py-3">
              <RouterLink
                :to="`/admin/nodes/${node.id}`"
                class="font-medium transition hover:text-accent-400"
              >
                {{ node.name }}
              </RouterLink>
              <div v-if="node.fqdn" class="font-mono text-xs text-ink-400">{{ node.fqdn }}</div>
            </td>
            <td class="px-4 py-3 text-ink-300">{{ node.location || "–" }}</td>
            <td class="px-4 py-3">
              <span class="inline-flex items-center gap-2 text-ink-300">
                <span class="h-2 w-2 rounded-full" :class="dots[node.status] ?? 'bg-ink-600'"></span>
                {{ statusLabel(node.status) }}
              </span>
            </td>
            <td class="px-4 py-3 font-mono text-xs text-ink-300">
              {{ node.port_range_start }}–{{ node.port_range_end }}
            </td>
            <td class="px-4 py-3 font-mono text-xs text-ink-300">{{ resources(node) }}</td>
            <td class="px-4 py-3 text-right">
              <button v-if="node.status === 'pending'" :class="buttonClass" @click="newToken(node)">
                {{ t("nodes.newToken") }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppLayout>
</template>
