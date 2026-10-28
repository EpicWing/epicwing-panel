<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import CountUp from "../components/CountUp.vue";

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

// Fest im Code, nicht im Panel einstellbar.
const HELP_URLS = {
  discord: "https://discord.gg/tc7xtNPsmh",
  docs: "",
  github: "",
  support: "",
};
const links: HelpLink[] = [
  { key: "discord", label: t("admin.linkDiscord"), url: HELP_URLS.discord },
  { key: "docs", label: t("admin.linkDocs"), url: HELP_URLS.docs },
  { key: "github", label: t("admin.linkGithub"), url: HELP_URLS.github },
  { key: "support", label: t("admin.linkSupport"), url: HELP_URLS.support },
];
const linkClass: Record<string, string> = {
  discord: "bg-amber-500 hover:bg-amber-400",
  docs: "bg-blue-600 hover:bg-blue-500",
  github: "bg-blue-600 hover:bg-blue-500",
  support: "bg-green-600 hover:bg-green-500",
};

const linkIcons: Record<string, string> = {
  discord: "M8 10h8M8 14h5M21 12a9 9 0 01-13.5 7.8L3 21l1.2-4.5A9 9 0 1121 12z",
  docs: "M12 6v13M12 6C10.5 4.8 8 4 5 4v13c3 0 5.5.8 7 2 1.5-1.2 4-2 7-2V4c-3 0-5.5.8-7 2z",
  github: "M8 8l-4 4 4 4M16 8l4 4-4 4M14 5l-4 14",
  support: "M12 20s-7-4.5-7-10a4 4 0 017-2.6A4 4 0 0119 10c0 5.5-7 10-7 10z",
};

async function load() {
  try {
    data.value = await api<Overview>("/admin/overview");
    failed.value = false;
  } catch {
    failed.value = true;
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


function ringClass(value: number | null): string {
  return value !== null && value >= 85 ? "stroke-bad" : "stroke-accent-500";
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
      text: cpu === null ? "–" : n.cpu_total ? `${+((cpu / 100) * n.cpu_total).toFixed(1)} of ${n.cpu_total} cores` : `${Math.round(cpu)} %`,
    },
    { key: "ram", label: t("admin.ram"), percent: percent(n.ram_used_mb, n.ram_total_mb), text: ram },
    { key: "disk", label: t("admin.disk"), percent: percent(n.disk_used_mb, n.disk_total_mb), text: disk },
  ];
}

onMounted(() => {
  void load();
  timer = window.setInterval(() => void load(), 10000);
});
onUnmounted(() => window.clearInterval(timer));
</script>

<template>
  <AppLayout area="admin" :title="t('admin.title')" :subtitle="t('admin.subtitle')">
    <p v-if="failed" role="alert" class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ t("admin.loadFailed") }}
    </p>

    <section class="mb-6">
      <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <component
          :is="link.url ? 'a' : 'span'"
          v-for="link in links"
          :key="link.key"
          :href="link.url || undefined"
          :target="link.url ? '_blank' : undefined"
          rel="noopener noreferrer"
          class="flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition"
          :class="link.url ? linkClass[link.key] : 'cursor-not-allowed bg-ink-800 opacity-50'"
        >
          <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path :d="linkIcons[link.key]" />
          </svg>
          {{ link.label }}
        </component>
      </div>
    </section>

    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="flex items-center gap-2 text-sm text-ink-400"><svg class="h-4 w-4 text-accent-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 6h16v5H4zM4 13h16v5H4zM8 8.5h.01M8 15.5h.01" /></svg>{{ t("admin.nodes") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold"><CountUp :value="data?.nodes.total" /></p>
        <p v-if="data" class="mt-1 text-xs text-ink-400">
          {{ t("admin.nodesOnline", { online: data.nodes.online, total: data.nodes.total }) }}
        </p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="flex items-center gap-2 text-sm text-ink-400"><svg class="h-4 w-4 text-accent-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h16v14H4zM8 10l3 2-3 2M13 14h3" /></svg>{{ t("admin.servers") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold"><CountUp :value="data?.servers.total" /></p>
        <p v-if="data" class="mt-1 text-xs text-ink-400">{{ t("admin.serversRunning", { running }) }}</p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="flex items-center gap-2 text-sm text-ink-400"><svg class="h-4 w-4 text-accent-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 19v-1a4 4 0 00-4-4H8a4 4 0 00-4 4v1M10 11a3 3 0 100-6 3 3 0 000 6zM20 19v-1a3 3 0 00-2-2.8" /></svg>{{ t("admin.users") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold"><CountUp :value="data?.users.total" /></p>
        <p v-if="data" class="mt-1 text-xs text-ink-400">
          {{ t("admin.usersDetail", { admins: data.users.admins, disabled: data.users.disabled }) }}
        </p>
      </div>
      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="flex items-center gap-2 text-sm text-ink-400"><svg class="h-4 w-4 text-accent-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h16v4H4zM5 9v10h14V9M10 13h4" /></svg>{{ t("admin.backups") }}</p>
        <p class="mt-1 font-mono text-2xl font-semibold"><CountUp :value="data?.backups.total" /></p>
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

    <h2 class="mt-10 text-xl font-semibold">{{ t("admin.systemTitle") }}</h2>
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
          <div class="mt-4 grid gap-4 sm:grid-cols-3">
            <div
              v-for="m in meters(n)"
              :key="m.key"
              class="flex items-center gap-5 rounded-lg border border-ink-700 bg-ink-950 p-4"
            >
              <div class="relative h-24 w-24 shrink-0">
                <svg viewBox="0 0 36 36" class="h-24 w-24 -rotate-90" aria-hidden="true">
                  <circle cx="18" cy="18" r="15.915" fill="none" stroke-width="3.2" class="stroke-ink-800" />
                  <circle
                    v-if="(m.percent ?? 0) > 0"
                    cx="18"
                    cy="18"
                    r="15.915"
                    fill="none"
                    stroke-width="3.2"
                    stroke-linecap="round"
                    class="transition-all"
                    :class="ringClass(m.percent)"
                    :stroke-dasharray="`${m.percent} 100`"
                  />
                </svg>
                <span class="absolute inset-0 flex items-center justify-center font-mono text-lg font-semibold">
                  {{ m.percent === null ? "–" : `${m.percent}%` }}
                </span>
              </div>
              <div class="min-w-0">
                <p class="text-sm text-ink-400">{{ m.label }}</p>
                <p class="mt-1 font-mono text-sm text-ink-300">{{ m.text }}</p>
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
