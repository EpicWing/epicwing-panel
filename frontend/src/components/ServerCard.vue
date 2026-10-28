<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

export interface ServerItem {
  id: string;
  name: string;
  address: string;
  status: "running" | "starting" | "offline";
  cpu: string;
  ram: string;
  storage: string;
}

const props = defineProps<{ server: ServerItem; demo?: boolean; layout?: "grid" | "list" }>();

const { t } = useI18n();

const dot = computed(
  () =>
    ({
      running: "bg-ok",
      starting: "bg-warn",
      offline: "bg-bad",
    })[props.server.status],
);

const stats = computed(() => [
  { label: t("servers.cpu"), value: props.server.cpu },
  { label: t("servers.ram"), value: props.server.ram },
  { label: t("servers.storage"), value: props.server.storage },
]);
</script>

<template>
  <div
    class="rounded-lg border border-ink-700 bg-ink-900 px-5 py-4 transition hover:border-ink-600 hover:bg-ink-800/60"
    :class="layout === 'list' ? 'flex flex-wrap items-center justify-between gap-x-8 gap-y-3' : ''"
  >
    <div class="min-w-0">
      <div class="flex items-center gap-2.5">
        <h3 class="truncate text-[15px] font-semibold">{{ server.name }}</h3>
        <span
          class="h-2 w-2 shrink-0 rounded-full"
          :class="dot"
          :title="t(`servers.status.${server.status}`)"
        ></span>
        <span
          v-if="demo"
          class="rounded border border-ink-600 px-1.5 text-[10px] uppercase tracking-wide text-ink-400"
        >
          {{ t("common.demo") }}
        </span>
      </div>
      <p class="mt-0.5 font-mono text-xs text-ink-400">{{ server.address }}</p>
    </div>

    <div
      class="flex items-center justify-center gap-5 rounded-md bg-ink-950 px-4 py-2 font-mono text-xs"
      :class="layout === 'list' ? '' : 'mt-4'"
    >
      <span v-for="stat in stats" :key="stat.label">
        <span class="text-ink-400">{{ stat.label }}</span>
        <span class="ml-1.5 font-semibold">{{ stat.value }}</span>
      </span>
    </div>
  </div>
</template>
