<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

interface NodeDetail {
  id: string;
  name: string;
  location: string;
  fqdn: string | null;
  status: string;
  last_heartbeat_at: string | null;
  cpu_total: number | null;
  ram_total_mb: number | null;
  disk_total_mb: number | null;
  agent_version: string | null;
  port_range_start: number;
  port_range_end: number;
  connected: boolean;
  fingerprint: string | null;
  registered_at: string | null;
  cpu_percent: number | null;
  ram_used_mb: number | null;
  disk_used_mb: number | null;
}

interface Enrollment {
  token: string;
  expires_at: string;
}

type Tab = "overview" | "settings" | "configuration" | "danger";
const tabs: Tab[] = ["overview", "settings", "configuration", "danger"];

const { t, te } = useI18n();
const route = useRoute();
const router = useRouter();
const nodeId = String(route.params.id);

const node = ref<NodeDetail | null>(null);
const tab = ref<Tab>("overview");
const error = ref("");
const notice = ref("");
const busy = ref(false);
const issued = ref<Enrollment | null>(null);
const copied = ref("");

const form = ref({ name: "", location: "", fqdn: "", portStart: 25000, portEnd: 25999 });

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const buttonClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100";
const primaryClass =
  "rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const dangerClass =
  "rounded-md border border-bad/50 px-3 py-1.5 text-sm text-bad transition hover:bg-bad/10 disabled:opacity-60";
const dots: Record<string, string> = { pending: "bg-warn", online: "bg-ok", offline: "bg-bad" };

let timer: number | undefined;

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

function statusLabel(status: string): string {
  const key = `nodes.status.${status}`;
  return te(key) ? t(key) : status;
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : t("nodeDetail.never");
}

function fillForm(n: NodeDetail) {
  form.value = {
    name: n.name,
    location: n.location,
    fqdn: n.fqdn ?? "",
    portStart: n.port_range_start,
    portEnd: n.port_range_end,
  };
}

async function load(first: boolean) {
  try {
    const result = await api<NodeDetail>(`/nodes/${nodeId}`);
    node.value = result;
    if (first) {
      fillForm(result);
    }
  } catch (e) {
    // A failed background refresh keeps the last data on screen.
    if (first || (e instanceof ApiError && e.status === 404)) {
      error.value = message(e);
    }
  }
}

function gb(mb: number | null): string {
  return mb === null ? "?" : (mb / 1024).toFixed(1);
}

function percent(used: number | null, total: number | null): number {
  if (used === null || total === null || total <= 0) {
    return 0;
  }
  return Math.min(100, Math.max(0, (used / total) * 100));
}

const usage = computed(() => {
  const n = node.value;
  if (!n) {
    return [];
  }
  const live = n.connected;
  const cpu = live ? n.cpu_percent : null;
  return [
    {
      key: "cpu",
      label: t("nodeDetail.cpu"),
      text:
        cpu === null
          ? "–"
          : `${cpu.toFixed(1)} % · ${t("nodeDetail.cores", { count: n.cpu_total ?? "?" })}`,
      percent: cpu ?? 0,
    },
    {
      key: "ram",
      label: t("nodeDetail.ram"),
      text: live && n.ram_used_mb !== null ? `${gb(n.ram_used_mb)} / ${gb(n.ram_total_mb)} GB` : "–",
      percent: live ? percent(n.ram_used_mb, n.ram_total_mb) : 0,
    },
    {
      key: "disk",
      label: t("nodeDetail.disk"),
      text:
        live && n.disk_used_mb !== null ? `${gb(n.disk_used_mb)} / ${gb(n.disk_total_mb)} GB` : "–",
      percent: live ? percent(n.disk_used_mb, n.disk_total_mb) : 0,
    },
  ];
});

const command = computed(() => {
  const token = issued.value?.token ?? "<token>";
  return `epicwing-agent enroll --panel <panel-url> --token '${token}'\nepicwing-agent run`;
});

async function copy(key: string, text: string) {
  try {
    await navigator.clipboard.writeText(text);
    copied.value = key;
  } catch {
    error.value = t("nodes.copyFailed");
  }
}

async function save() {
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    const result = await api<NodeDetail>(`/nodes/${nodeId}`, {
      method: "PATCH",
      body: {
        name: form.value.name,
        location: form.value.location,
        fqdn: form.value.fqdn.trim() || null,
        port_range_start: Number(form.value.portStart),
        port_range_end: Number(form.value.portEnd),
      },
    });
    node.value = result;
    fillForm(result);
    notice.value = t("nodeDetail.saved");
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function newToken() {
  error.value = "";
  try {
    issued.value = await api<Enrollment>(`/nodes/${nodeId}/enrollment`, { method: "POST" });
    copied.value = "";
  } catch (e) {
    error.value = message(e);
  }
}

async function revoke() {
  if (!node.value || !window.confirm(t("nodeDetail.revokeConfirm", { name: node.value.name }))) {
    return;
  }
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    node.value = await api<NodeDetail>(`/nodes/${nodeId}/revoke`, { method: "POST" });
    issued.value = null;
    notice.value = t("nodeDetail.revoked");
    tab.value = "configuration";
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function remove() {
  if (!node.value || !window.confirm(t("nodeDetail.deleteConfirm", { name: node.value.name }))) {
    return;
  }
  error.value = "";
  busy.value = true;
  try {
    await api<void>(`/nodes/${nodeId}`, { method: "DELETE" });
    await router.push("/admin/nodes");
  } catch (e) {
    error.value = message(e);
    busy.value = false;
  }
}

onMounted(() => {
  void load(true);
  timer = window.setInterval(() => void load(false), 5000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <AppLayout
    area="admin"
    :title="node?.name ?? t('nodeDetail.loading')"
    :subtitle="node?.location || ''"
  >
    <template #actions>
      <RouterLink to="/admin/nodes" :class="buttonClass">{{ t("nodeDetail.back") }}</RouterLink>
    </template>

    <p
      v-if="error"
      role="alert"
      class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      class="mb-6 rounded-md border border-ok/40 bg-ok/10 px-3 py-2 text-sm text-ok"
    >
      {{ notice }}
    </p>

    <template v-if="node">
      <nav class="mb-6 flex gap-1 overflow-x-auto border-b border-ink-700">
        <button
          v-for="name in tabs"
          :key="name"
          class="whitespace-nowrap border-b-2 px-4 py-2 text-sm transition"
          :class="
            tab === name
              ? 'border-accent-500 text-ink-100'
              : 'border-transparent text-ink-400 hover:text-ink-100'
          "
          @click="tab = name"
        >
          {{ t(`nodeDetail.tabs.${name}`) }}
        </button>
      </nav>

      <section v-if="tab === 'overview'" class="space-y-6">
        <div class="grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5 sm:grid-cols-2">
          <div>
            <p class="text-xs uppercase tracking-wider text-ink-400">{{ t("nodeDetail.status") }}</p>
            <p class="mt-1 inline-flex items-center gap-2 text-sm">
              <span class="h-2 w-2 rounded-full" :class="dots[node.status] ?? 'bg-ink-600'"></span>
              {{ statusLabel(node.status) }}
            </p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wider text-ink-400">
              {{ t("nodeDetail.agentVersion") }}
            </p>
            <p class="mt-1 font-mono text-sm">{{ node.agent_version ?? "–" }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wider text-ink-400">
              {{ t("nodeDetail.lastHeartbeat") }}
            </p>
            <p class="mt-1 text-sm">{{ formatDate(node.last_heartbeat_at) }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wider text-ink-400">
              {{ t("nodeDetail.registered") }}
            </p>
            <p class="mt-1 text-sm">{{ formatDate(node.registered_at) }}</p>
          </div>
          <div class="sm:col-span-2">
            <p class="text-xs uppercase tracking-wider text-ink-400">
              {{ t("nodeDetail.address") }}
            </p>
            <p class="mt-1 font-mono text-sm">{{ node.fqdn ?? "–" }}</p>
          </div>
        </div>

        <div class="space-y-4 rounded-lg border border-ink-700 bg-ink-900 p-5">
          <p v-if="!node.connected" class="text-sm text-ink-400">
            {{ t("nodeDetail.notConnected") }}
          </p>
          <div v-for="row in usage" :key="row.key">
            <div class="mb-1.5 flex items-baseline justify-between text-sm">
              <span class="text-ink-300">{{ row.label }}</span>
              <span class="font-mono text-xs text-ink-300">{{ row.text }}</span>
            </div>
            <div class="h-1.5 w-full rounded bg-ink-700">
              <div
                class="h-1.5 rounded bg-accent-500 transition-all"
                :style="{ width: `${row.percent}%` }"
              ></div>
            </div>
          </div>
        </div>
      </section>

      <form
        v-else-if="tab === 'settings'"
        class="grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5 sm:grid-cols-2"
        @submit.prevent="save"
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
        <div>
          <label for="port-start" class="mb-1.5 block text-sm text-ink-300">
            {{ t("nodes.portStart") }}
          </label>
          <input
            id="port-start"
            v-model.number="form.portStart"
            required
            type="number"
            min="1024"
            max="65535"
            :class="inputClass"
          />
        </div>
        <div>
          <label for="port-end" class="mb-1.5 block text-sm text-ink-300">
            {{ t("nodes.portEnd") }}
          </label>
          <input
            id="port-end"
            v-model.number="form.portEnd"
            required
            type="number"
            min="1024"
            max="65535"
            :class="inputClass"
          />
        </div>
        <p class="text-xs text-ink-400 sm:col-span-2">{{ t("nodeDetail.portsHint") }}</p>
        <div class="sm:col-span-2">
          <button type="submit" :disabled="busy" :class="primaryClass">
            {{ busy ? t("nodeDetail.saving") : t("nodeDetail.save") }}
          </button>
        </div>
      </form>

      <section v-else-if="tab === 'configuration'" class="space-y-6">
        <div class="grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5">
          <div>
            <p class="text-xs uppercase tracking-wider text-ink-400">{{ t("nodeDetail.nodeId") }}</p>
            <p class="mt-1 break-all font-mono text-sm">{{ node.id }}</p>
          </div>
          <div>
            <p class="text-xs uppercase tracking-wider text-ink-400">
              {{ t("nodeDetail.fingerprint") }}
            </p>
            <p class="mt-1 break-all font-mono text-xs">{{ node.fingerprint ?? "–" }}</p>
            <p class="mt-1.5 text-xs text-ink-400">{{ t("nodeDetail.fingerprintHint") }}</p>
          </div>
        </div>

        <div class="rounded-lg border border-ink-700 bg-ink-900 p-5">
          <p class="font-medium">{{ t("nodeDetail.setupTitle") }}</p>
          <p class="mt-1 text-sm text-ink-300">{{ t("nodeDetail.setupBody") }}</p>
          <pre
            class="mt-3 overflow-x-auto rounded-md border border-ink-700 bg-ink-950 p-3 font-mono text-xs"
            >{{ command }}</pre
          >
          <div class="mt-3 flex flex-wrap items-center gap-2">
            <button :class="buttonClass" @click="copy('command', command)">
              {{ copied === "command" ? t("nodes.copied") : t("nodeDetail.copyCommand") }}
            </button>
            <button v-if="node.status === 'pending'" :class="buttonClass" @click="newToken">
              {{ t("nodes.newToken") }}
            </button>
          </div>
          <p v-if="issued" class="mt-3 text-xs text-ink-400">
            {{ t("nodes.tokenBody", { date: formatDate(issued.expires_at) }) }}
          </p>
          <p v-else-if="node.status !== 'pending'" class="mt-3 text-xs text-ink-400">
            {{ t("nodeDetail.alreadyRegistered") }}
          </p>
        </div>
      </section>

      <section v-else class="space-y-4">
        <div
          class="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-bad/40 p-5"
        >
          <div class="max-w-xl">
            <p class="font-medium">{{ t("nodeDetail.revokeTitle") }}</p>
            <p class="mt-1 text-sm text-ink-300">{{ t("nodeDetail.revokeBody") }}</p>
          </div>
          <button :class="dangerClass" :disabled="busy || node.status === 'pending'" @click="revoke">
            {{ t("nodeDetail.revoke") }}
          </button>
        </div>
        <div
          class="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-bad/40 p-5"
        >
          <div class="max-w-xl">
            <p class="font-medium">{{ t("nodeDetail.deleteTitle") }}</p>
            <p class="mt-1 text-sm text-ink-300">{{ t("nodeDetail.deleteBody") }}</p>
          </div>
          <button :class="dangerClass" :disabled="busy" @click="remove">
            {{ t("nodeDetail.delete") }}
          </button>
        </div>
      </section>
    </template>
  </AppLayout>
</template>
