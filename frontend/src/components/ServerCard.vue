<script setup lang="ts">
import { computed, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ui } from "../stores/ui";

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

const stats = computed(() => [
  { label: t("servers.cpu"), value: props.server.cpu, pct: props.server.cpuPct },
  { label: t("servers.ram"), value: props.server.ram, pct: props.server.ramPct },
  { label: t("servers.storage"), value: props.server.storage, pct: props.server.diskPct },
]);

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
    class="rounded-xl border border-ink-700 bg-ink-900 p-6 transition hover:border-ink-600 hover:bg-ink-800/50"
    :class="layout === 'list' ? 'flex flex-wrap items-center justify-between gap-x-8 gap-y-4' : ''"
  >
    <div class="min-w-0">
      <div class="flex items-center gap-3">
        <h3 class="truncate text-lg font-semibold">{{ server.name }}</h3>
        <span
          v-if="demo"
          class="rounded border border-ink-600 px-1.5 text-[10px] uppercase tracking-wide text-ink-400"
        >
          {{ t("common.demo") }}
        </span>
      </div>

      <div class="mt-2 flex items-center gap-2">
        <span class="h-2.5 w-2.5 shrink-0 rounded-full" :class="dot"></span>
        <span class="text-sm text-ink-300">{{ t(`servers.status.${server.status}`) }}</span>
      </div>

      <div class="mt-3 flex items-center gap-3">
        <div class="min-w-0">
          <p
            v-if="ui.state.mode === 'simple'"
            class="text-[11px] uppercase tracking-wider text-ink-400"
          >
            {{ t("servers.connectWith") }}
          </p>
          <p class="truncate font-mono text-sm text-ink-300">{{ server.address }}</p>
        </div>
        <button
          class="shrink-0 rounded-md border border-ink-700 px-2.5 py-1 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100"
          @click="copyAddress"
        >
          {{ copied ? t("servers.copied") : t("servers.copy") }}
        </button>
      </div>
    </div>

    <div
      class="grid grid-cols-3 gap-3"
      :class="layout === 'list' ? 'w-full sm:w-auto sm:min-w-[22rem]' : 'mt-5'"
    >
      <div v-for="stat in stats" :key="stat.label" class="rounded-lg bg-ink-950 px-3.5 py-3">
        <p class="text-xs text-ink-400">{{ stat.label }}</p>
        <p class="mt-1 font-mono text-base font-semibold">{{ stat.value }}</p>
        <div
          v-if="stat.pct !== undefined"
          class="mt-2 h-1 overflow-hidden rounded-full bg-ink-700"
        >
          <div
            class="h-full rounded-full"
            :class="barColor(stat.pct)"
            :style="{ width: `${Math.min(100, Math.max(0, stat.pct))}%` }"
          ></div>
        </div>
      </div>
    </div>
  </div>
</template>
