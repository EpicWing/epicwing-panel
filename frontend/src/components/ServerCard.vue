<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

export interface ServerItem {
  id: string;
  name: string;
  address: string;
  status: "running" | "starting" | "offline";
  cpu: string;
  ram: string;
  storage: string;
  cpuPct?: number;
  ramPct?: number;
  diskPct?: number;
}

const props = defineProps<{ server: ServerItem; demo?: boolean; layout?: "grid" | "list" }>();
const emit = defineEmits<{ open: [id: string] }>();

const { t } = useI18n();
const copied = ref(false);

const dot = computed(
  () =>
    ({
      running: "bg-ok",
      starting: "bg-warn",
      offline: "bg-bad",
    })[props.server.status],
);

const stats = computed(() => {
  const off = props.server.status === "offline";
  const offline = t("servers.status.offline");
  return [
    { label: t("servers.cpu"), value: off ? offline : props.server.cpu, pct: off ? undefined : props.server.cpuPct },
    { label: t("servers.ram"), value: off ? offline : props.server.ram, pct: off ? undefined : props.server.ramPct },
    { label: t("servers.storage"), value: off ? offline : props.server.storage, pct: off ? undefined : props.server.diskPct },
  ];
});

function barColor(pct: number): string {
  if (pct >= 90) {
    return "bg-bad";
  }
  return pct >= 70 ? "bg-warn" : "bg-accent-500";
}

async function copyAddress() {
  try {
    await navigator.clipboard.writeText(props.server.address);
    copied.value = true;
    setTimeout(() => {
      copied.value = false;
    }, 1500);
  } catch {
    // Clipboard is not available, nothing to do.
  }
}
</script>

<template>
  <div
    class="relative cursor-pointer overflow-hidden rounded-2xl border border-ink-700 bg-ink-800 transition duration-200 hover:-translate-y-0.5 hover:border-ink-600 hover:shadow-lg hover:shadow-black/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
    :class="
      layout === 'list'
        ? 'flex flex-wrap items-center justify-between gap-x-8 gap-y-4 px-5 py-4'
        : 'p-6'
    "
    role="button"
    tabindex="0"
    @click="emit('open', server.id)"
    @keydown.enter="emit('open', server.id)"
    @keydown.space.prevent="emit('open', server.id)"
  >
    <div class="min-w-0" :class="layout === 'list' ? 'flex-1 basis-64' : ''">
      <div class="flex items-start justify-between gap-3">
        <div class="flex min-w-0 items-center gap-2">
          <h3
            class="truncate text-lg font-semibold"
            :class="server.status === 'offline' ? 'text-ink-300' : ''"
          >
            {{ server.name }}
          </h3>
          <span
            v-if="demo"
            class="shrink-0 rounded border border-ink-600 px-1.5 text-[10px] uppercase tracking-wide text-ink-400"
          >
            {{ t("common.demo") }}
          </span>
        </div>
        <span class="inline-flex shrink-0 items-center gap-1.5 pt-1 text-xs text-ink-300">
          <span class="h-2 w-2 rounded-full transition-colors duration-500" :class="dot"></span>
          {{ t(`servers.status.${server.status}`) }}
        </span>
      </div>

      <button
        type="button"
        class="group mt-3 flex w-full items-center justify-between gap-3 rounded-lg bg-ink-950 px-3 py-1.5 text-left transition hover:bg-ink-900"
        :title="t('servers.connectWith')"
        @click.stop="copyAddress"
      >
        <span class="min-w-0 truncate font-mono text-sm text-ink-300">{{ server.address }}</span>
        <span
          class="shrink-0 text-xs transition"
          :class="
            copied
              ? 'text-accent-400'
              : 'text-ink-400 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100'
          "
        >
          {{ copied ? t("servers.copied") : t("servers.copy") }}
        </span>
      </button>
    </div>

    <div
      class="grid grid-cols-3 gap-4"
      :class="layout === 'list' ? 'w-full sm:w-auto sm:min-w-[22rem]' : 'mt-5'"
    >
      <div v-for="stat in stats" :key="stat.label">
        <p class="text-xs text-ink-400">{{ stat.label }}</p>
        <p
          class="mt-0.5 font-mono text-sm font-semibold"
          :class="server.status === 'offline' ? 'text-ink-400' : ''"
        >
          {{ stat.value }}
        </p>
        <div
          v-if="stat.pct !== undefined"
          class="mt-2 h-1.5 overflow-hidden rounded-full bg-ink-950"
        >
          <div
            class="h-full rounded-full transition-[width,background-color] duration-700 ease-out"
            :class="barColor(stat.pct)"
            :style="{ width: `${Math.min(100, Math.max(0, stat.pct))}%` }"
          ></div>
        </div>
      </div>
    </div>
  </div>
</template>
