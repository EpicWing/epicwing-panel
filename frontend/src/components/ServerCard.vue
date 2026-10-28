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

const props = defineProps<{ server: ServerItem; demo?: boolean }>();

const { t } = useI18n();

const dot = computed(
  () =>
    ({
      running: "bg-ok",
      starting: "bg-warn",
      offline: "bg-bad",
    })[props.server.status],
);
</script>

<template>
  <div class="rounded-lg border border-ink-700 bg-ink-900 p-4 transition hover:border-ink-600">
    <div class="flex items-center gap-2">
      <span class="h-2 w-2 shrink-0 rounded-full" :class="dot"></span>
      <h3 class="truncate font-medium">{{ server.name }}</h3>
      <span
        v-if="demo"
        class="ml-auto rounded border border-ink-600 px-1.5 text-[10px] uppercase tracking-wide text-ink-400"
      >
        {{ t("common.demo") }}
      </span>
    </div>
    <p class="mt-1 font-mono text-xs text-ink-400">{{ server.address }}</p>

    <dl
      class="mt-4 grid grid-cols-3 divide-x divide-ink-700 rounded-md border border-ink-700 bg-ink-950 text-center font-mono text-xs"
    >
      <div class="px-2 py-2">
        <dt class="text-ink-400">{{ t("servers.cpu") }}</dt>
        <dd class="mt-0.5">{{ server.cpu }}</dd>
      </div>
      <div class="px-2 py-2">
        <dt class="text-ink-400">{{ t("servers.ram") }}</dt>
        <dd class="mt-0.5">{{ server.ram }}</dd>
      </div>
      <div class="px-2 py-2">
        <dt class="text-ink-400">{{ t("servers.storage") }}</dt>
        <dd class="mt-0.5">{{ server.storage }}</dd>
      </div>
    </dl>
  </div>
</template>
