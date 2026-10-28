<script setup lang="ts">
import { onMounted, ref } from "vue";

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

const emptyForm = {
  name: "",
  location: "",
  fqdn: "",
  port_range_start: 25000,
  port_range_end: 25999,
};

const nodes = ref<NodeItem[]>([]);
const loading = ref(true);
const error = ref("");
const showForm = ref(false);
const busy = ref(false);
const form = ref({ ...emptyForm });
const issued = ref<{ nodeName: string; enrollment: Enrollment } | null>(null);
const copied = ref(false);

const statusLabels: Record<string, string> = {
  pending: "Wartet auf Agent",
  online: "Online",
  offline: "Offline",
};

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Der Server ist nicht erreichbar.";
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString("de-DE");
}

function resources(node: NodeItem): string {
  if (node.cpu_total === null || node.ram_total_mb === null) {
    return "–";
  }
  const ram = Math.round(node.ram_total_mb / 1024);
  return `${node.cpu_total} CPU · ${ram} GB RAM`;
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
  busy.value = true;
  try {
    const result = await api<{ node: NodeItem; enrollment: Enrollment }>("/nodes", {
      method: "POST",
      body: {
        name: form.value.name,
        location: form.value.location,
        fqdn: form.value.fqdn.trim() || null,
        port_range_start: form.value.port_range_start,
        port_range_end: form.value.port_range_end,
      },
    });
    nodes.value.push(result.node);
    issued.value = { nodeName: result.node.name, enrollment: result.enrollment };
    copied.value = false;
    showForm.value = false;
    form.value = { ...emptyForm };
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
    error.value = "Kopieren nicht möglich, bitte den Token von Hand markieren.";
  }
}

onMounted(load);
</script>

<template>
  <AppLayout title="Nodes">
    <div class="mb-6 flex items-center justify-between gap-4">
      <p class="text-sm text-slate-400">Server, auf denen später Projekte laufen.</p>
      <button
        class="shrink-0 rounded-lg bg-indigo-500 px-3 py-2 text-sm font-medium transition hover:bg-indigo-400"
        @click="showForm = !showForm"
      >
        {{ showForm ? "Abbrechen" : "Node hinzufügen" }}
      </button>
    </div>

    <p
      v-if="error"
      role="alert"
      class="mb-6 rounded-lg border border-red-900 bg-red-950 px-3 py-2 text-sm text-red-300"
    >
      {{ error }}
    </p>

    <div
      v-if="issued"
      class="mb-6 rounded-xl border border-indigo-900 bg-indigo-950/40 p-4 text-sm"
    >
      <p class="font-medium">Enrollment-Token für „{{ issued.nodeName }}“</p>
      <p class="mt-1 text-slate-300">
        Er wird nur jetzt angezeigt und ist bis {{ formatDate(issued.enrollment.expires_at) }}
        gültig. Der Node-Agent ist noch nicht implementiert, der Token kann deshalb noch nicht
        verwendet werden.
      </p>
      <div class="mt-3 flex flex-wrap items-center gap-2">
        <code class="min-w-0 flex-1 break-all rounded-lg bg-slate-950 px-3 py-2 text-xs">
          {{ issued.enrollment.token }}
        </code>
        <button
          class="rounded-lg border border-slate-700 px-3 py-1.5 transition hover:bg-slate-800"
          @click="copyToken"
        >
          {{ copied ? "Kopiert" : "Kopieren" }}
        </button>
        <button
          class="rounded-lg border border-slate-700 px-3 py-1.5 transition hover:bg-slate-800"
          @click="issued = null"
        >
          Schließen
        </button>
      </div>
    </div>

    <form
      v-if="showForm"
      class="mb-6 grid gap-4 rounded-xl border border-slate-800 bg-slate-900 p-5 sm:grid-cols-2"
      @submit.prevent="create"
    >
      <div>
        <label for="name" class="mb-1 block text-sm text-slate-300">Name</label>
        <input
          id="name"
          v-model="form.name"
          required
          maxlength="64"
          class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
      </div>
      <div>
        <label for="location" class="mb-1 block text-sm text-slate-300">Standort</label>
        <input
          id="location"
          v-model="form.location"
          maxlength="64"
          placeholder="z. B. Germany"
          class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
      </div>
      <div class="sm:col-span-2">
        <label for="fqdn" class="mb-1 block text-sm text-slate-300">Hostname (optional)</label>
        <input
          id="fqdn"
          v-model="form.fqdn"
          placeholder="node1.example.com"
          class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
      </div>
      <div>
        <label for="port-start" class="mb-1 block text-sm text-slate-300">Port-Bereich ab</label>
        <input
          id="port-start"
          v-model.number="form.port_range_start"
          type="number"
          min="1024"
          max="65535"
          required
          class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
      </div>
      <div>
        <label for="port-end" class="mb-1 block text-sm text-slate-300">Port-Bereich bis</label>
        <input
          id="port-end"
          v-model.number="form.port_range_end"
          type="number"
          min="1024"
          max="65535"
          required
          class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
      </div>
      <div class="sm:col-span-2">
        <button
          type="submit"
          :disabled="busy"
          class="rounded-lg bg-indigo-500 px-4 py-2 text-sm font-medium transition hover:bg-indigo-400 disabled:opacity-60"
        >
          {{ busy ? "Anlegen …" : "Node anlegen" }}
        </button>
      </div>
    </form>

    <div class="overflow-x-auto rounded-xl border border-slate-800">
      <table class="w-full text-left text-sm">
        <thead class="bg-slate-900 text-slate-400">
          <tr>
            <th class="px-4 py-3 font-medium">Name</th>
            <th class="px-4 py-3 font-medium">Standort</th>
            <th class="px-4 py-3 font-medium">Status</th>
            <th class="px-4 py-3 font-medium">Ports</th>
            <th class="px-4 py-3 font-medium">Ressourcen</th>
            <th class="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-800">
          <tr v-if="loading">
            <td colspan="6" class="px-4 py-6 text-center text-slate-500">Lade …</td>
          </tr>
          <tr v-else-if="nodes.length === 0">
            <td colspan="6" class="px-4 py-6 text-center text-slate-500">
              Noch keine Nodes angelegt.
            </td>
          </tr>
          <tr v-for="node in nodes" :key="node.id">
            <td class="px-4 py-3">
              <div class="font-medium">{{ node.name }}</div>
              <div v-if="node.fqdn" class="text-xs text-slate-500">{{ node.fqdn }}</div>
            </td>
            <td class="px-4 py-3 text-slate-300">{{ node.location || "–" }}</td>
            <td class="px-4 py-3">
              <span class="rounded-full bg-slate-800 px-2 py-0.5 text-xs text-slate-300">
                {{ statusLabels[node.status] ?? node.status }}
              </span>
            </td>
            <td class="px-4 py-3 text-slate-300">
              {{ node.port_range_start }}–{{ node.port_range_end }}
            </td>
            <td class="px-4 py-3 text-slate-300">{{ resources(node) }}</td>
            <td class="px-4 py-3 text-right">
              <button
                v-if="node.status === 'pending'"
                class="rounded-lg border border-slate-700 px-3 py-1.5 text-xs transition hover:bg-slate-800"
                @click="newToken(node)"
              >
                Neuer Token
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </AppLayout>
</template>
