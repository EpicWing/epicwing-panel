<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

interface NodeLoad {
  id: string;
  name: string;
  status: string;
  cpu_total: number | null;
  ram_total_mb: number | null;
  disk_total_mb: number | null;
  cpu_percent: number | null;
  ram_used_mb: number | null;
  disk_used_mb: number | null;
  servers: number;
  ram_allocated_mb: number;
  disk_allocated_mb: number;
}

interface Overview {
  nodes: { total: number; online: number; offline: number; pending: number };
  servers: { total: number; by_status: Record<string, number> };
  users: { total: number; admins: number; disabled: number };
  backups: { total: number; running: number; failed: number; size_bytes: number };
  node_load: NodeLoad[];
}

const { t } = useI18n();
const data = ref<Overview | null>(null);
const failed = ref(false);
let timer: number | undefined;

interface HelpLink {
  key: string;
  label: string;
  url: string;
}

const links = ref<HelpLink[]>([]);
const linksLoaded = ref(false);
const linkClass: Record<string, string> = {
  discord: "bg-amber-500 hover:bg-amber-400",
  docs: "bg-blue-600 hover:bg-blue-500",
  github: "bg-blue-600 hover:bg-blue-500",
  support: "bg-green-600 hover:bg-green-500",
};

async function load() {
  try {
    data.value = await api<Overview>("/admin/overview");
    failed.value = false;
  } catch {
    failed.value = true;
  }
}

async function loadLinks() {
  try {
    const s = await api<Record<string, string>>("/admin/settings");
    links.value = [
      { key: "discord", label: t("admin.linkDiscord"), url: s.discord_url },
      { key: "docs", label: t("admin.linkDocs"), url: s.docs_url },
      { key: "github", label: t("admin.linkGithub"), url: s.github_url },
      { key: "support", label: t("admin.linkSupport"), url: s.support_url },
    ].filter((link) => link.url);
    linksLoaded.value = true;
  } catch {
    // The quick links are optional.
  }
}

const steps = computed(() => [
  {
    title: t("admin.step1Title"),
    body: t("admin.step1Body"),
    done: (data.value?.nodes.total ?? 0) > 0,
    to: "/admin/nodes",
  },
  {
    title: t("admin.step2Title"),
    body: t("admin.step2Body"),
    done: (data.value?.nodes.online ?? 0) > 0,
    to: "/admin/nodes",
  },
  {
    title: t("admin.step3Title"),
    body: t("admin.step3Body"),
    done: (data.value?.servers.total ?? 0) > 0,
    to: "/admin/servers",
  },
]);

// The checklist disappears on its own once every step is done.
const allDone = computed(() => steps.value.every((step) => step.done));
const running = computed(() => data.value?.servers.by_status.running ?? 0);
const statusEntries = computed(() =>
  Object.entries(data.value?.servers.by_status ?? {}).sort((a, b) => b[1] - a[1]),
);

const dots: Record<string, string> = { online: "bg-ok", offline: "bg-bad", pending: "bg-warn" };

function size(mb: number): string {
  return mb >= 1024 ? `${+(mb / 1024).toFixed(1)} GiB` : `${Math.round(mb)} MiB`;
}

function percent(used: number | null, total: number | null): number | null {
  if (used === null || !total) return null;
  return Math.min(100, Math.round((used / total) * 100));
}

function barClass(value: number | null): string {
  return value !== null && value >= 85 ? "bg-bad" : "bg-accent-500";
}

function meters(n: NodeLoad) {
  const cpu = n.cpu_percent;
  const ram = n.ram_used_mb !== null && n.ram_total_mb ? `${size(n.ram_used_mb)} / ${size(n.ram_total_mb)}` : "–";
  const disk =
    n.disk_used_mb !== null && n.disk_total_mb ? `${size(n.disk_used_mb)} / ${size(n.disk_total_mb)}` : "–";
  return [
    {
      key: "cpu",
      label: t("admin.cpu"),
      percent: cpu === null ? null : Math.min(100, Math.round(cpu)),
      text: cpu === null ? "–" : `${Math.round(cpu)} %${n.cpu_total ? ` of ${n.cpu_total} cores` : ""}`,
    },
    { key: "ram", label: t("admin.ram"), percent: percent(n.ram_used_mb, n.ram_total_mb), text: ram },
    { key: "disk", label: t("admin.disk"), percent: percent(n.disk_used_mb, n.disk_total_mb), text: disk },
  ];
}

onMounted(() => {
  void load();
  void loadLinks();
  timer = window.setInterval(() => void load(), 10000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <AppLayout area="admin" :title="t('admin.title')" :subtitle="t('admin.subtitle')">
    <p v-if="failed" role="alert" class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ t("admin.loadFailed") }}
    </p>

    <section v-if="linksLoaded" class="mb-6">
      <div v-if="links.length" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <a
          v-for="link in links"
          :key="link.key"
          :href="link.url"
          target="_blank"
          rel="noopener noreferrer"
          class="rounded-lg px-4 py-2.5 text-center text-sm font-semibold text-white transition" :class="linkClass[link.key]"
        >
          {{ link.label }}
        </a>
      </div>
      <p v-else class="text-sm text-ink-400">
        {{ t("admin.linksEmpty") }}
        <RouterLink to="/admin/settings" class="text-accent-400 hover:underline">{{ t("admin.linksAdd") }}</RouterLink>
      </p>
    </section>

    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="text-sm text-ink-400">{{ t("admin.nodes") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold">{{ data?.nodes.total ?? "–" }}</p>
        <p v-if="data" class="mt-1 text-xs text-ink-400">
          {{ t("admin.nodesOnline", { online: data.nodes.online, total: data.nodes.total }) }}
        </p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="text-sm text-ink-400">{{ t("admin.servers") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold">{{ data?.servers.total ?? "–" }}</p>
        <p v-if="data" class="mt-1 text-xs text-ink-400">{{ t("admin.serversRunning", { running }) }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="text-sm text-ink-400">{{ t("admin.users") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold">{{ data?.users.total ?? "–" }}</p>
        <p v-if="data" class="mt-1 text-xs text-ink-400">
          {{ t("admin.usersDetail", { admins: data.users.admins, disabled: data.users.disabled }) }}
        </p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="text-sm text-ink-400">{{ t("admin.backups") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold">{{ data?.backups.total ?? "–" }}</p>
        <p v-if="data" class="mt-1 text-xs" :class="data.backups.failed ? 'text-bad' : 'text-ink-400'">
          {{
            t("admin.backupsDetail", {
              running: data.backups.running,
              failed: data.backups.failed,
              size: size(data.backups.size_bytes / 1048576),
            })
          }}
        </p>
      </div>
    </div>

    <section v-if="statusEntries.length" class="mt-8">
      <h2 class="mb-3 text-lg font-semibold">{{ t("admin.statusTitle") }}</h2>
      <ul class="flex flex-wrap gap-2">
        <li
          v-for="[name, count] in statusEntries"
          :key="name"
          class="rounded-full border border-ink-700 bg-ink-900 px-3 py-1 text-xs text-ink-300"
        >
          <span class="font-mono text-ink-100">{{ count }}</span> {{ name }}
        </li>
      </ul>
    </section>

    <section v-if="data" class="mt-8">
      <h2 class="mb-3 text-lg font-semibold">{{ t("admin.loadTitle") }}</h2>
      <p v-if="data.node_load.length === 0" class="text-sm text-ink-400">{{ t("admin.loadEmpty") }}</p>
      <ul v-else class="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
        <li v-for="n in data.node_load" :key="n.id" class="p-5">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <p class="font-medium">
              <span class="mr-2 inline-block h-2 w-2 rounded-full" :class="dots[n.status] ?? 'bg-ink-600'" />{{ n.name }}
            </p>
            <p class="text-xs text-ink-400">
              {{
                t("admin.allocated", {
                  count: n.servers,
                  ram: size(n.ram_allocated_mb),
                  disk: size(n.disk_allocated_mb),
                })
              }}
            </p>
          </div>
          <p v-if="n.status !== 'online'" class="mt-1 text-xs text-ink-400">{{ t("admin.noLive") }}</p>
          <div class="mt-3 grid gap-4 sm:grid-cols-3">
            <div v-for="m in meters(n)" :key="m.key">
              <div class="flex justify-between text-xs text-ink-400">
                <span>{{ m.label }}</span>
                <span class="font-mono text-ink-300">{{ m.text }}</span>
              </div>
              <div class="mt-1.5 h-1.5 overflow-hidden rounded-full bg-ink-800">
                <div
                  class="h-full rounded-full transition-all"
                  :class="barClass(m.percent)"
                  :style="{ width: `${m.percent ?? 0}%` }"
                />
              </div>
            </div>
          </div>
        </li>
      </ul>
    </section>

    <section v-if="data && !allDone" class="mt-8">
      <h2 class="mb-4 text-lg font-semibold">{{ t("admin.startTitle") }}</h2>
      <ol class="divide-y divide-ink-700 rounded-xl border border-ink-700 bg-ink-900">
        <li v-for="(step, index) in steps" :key="step.title" class="flex items-center gap-4 p-5">
          <span
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-semibold"
            :class="step.done ? 'border-ok/50 bg-ok/10 text-ok' : 'border-ink-600 text-ink-400'"
          >
            {{ step.done ? "✓" : index + 1 }}
          </span>
          <div class="min-w-0 flex-1">
            <p class="font-medium">{{ step.title }}</p>
            <p class="text-sm text-ink-400">{{ step.body }}</p>
          </div>
          <span v-if="step.done" class="text-xs text-ok">{{ t("admin.stepDone") }}</span>
          <RouterLink
            v-else
            :to="step.to"
            class="rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100"
          >
            {{ t("admin.stepOpen") }}
          </RouterLink>
        </li>
      </ol>
    </section>
  </AppLayout>
</template>
