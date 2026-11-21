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

const tone = computed(
  () =>
    ({
      running: {
        text: "text-ok",
        dot: "bg-ok",
        pill: "bg-ok/10 ring-ok/25",
        line: "via-ok/70",
        glow: "from-ok/[0.08]",
        tile: "bg-ok/10 text-ok ring-ok/20",
      },
      starting: {
        text: "text-warn",
        dot: "bg-warn",
        pill: "bg-warn/10 ring-warn/25",
        line: "via-warn/70",
        glow: "from-warn/[0.08]",
        tile: "bg-warn/10 text-warn ring-warn/20",
      },
      offline: {
        text: "text-bad",
        dot: "bg-bad",
        pill: "bg-bad/10 ring-bad/25",
        line: "via-bad/40",
        glow: "from-bad/[0.05]",
        tile: "bg-bad/10 text-bad ring-bad/20",
      },
    })[props.server.status],
);

const ICONS = {
  cpu: "M9 9h6v6H9z M6 5h12a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z M9 2v3 M15 2v3 M9 19v3 M15 19v3 M2 9h3 M2 15h3 M19 9h3 M19 15h3",
  ram: "M4 7h16a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z M6 11v2 M10 11v2 M14 11v2 M18 11v2 M6 17v3 M18 17v3",
  storage:
    "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3z M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6 M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
} as const;

const stats = computed(() => {
  const off = props.server.status === "offline";
  const offline = t("servers.status.offline");
  return [
    { key: "cpu", icon: ICONS.cpu, label: t("servers.cpu"), value: off ? offline : props.server.cpu, pct: off ? undefined : props.server.cpuPct },
    { key: "ram", icon: ICONS.ram, label: t("servers.ram"), value: off ? offline : props.server.ram, pct: off ? undefined : props.server.ramPct },
    { key: "storage", icon: ICONS.storage, label: t("servers.storage"), value: off ? props.server.storage || offline : props.server.storage, pct: off ? undefined : props.server.diskPct },
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
    class="group/card relative cursor-pointer overflow-hidden rounded-2xl border border-ink-700 bg-ink-800 transition duration-200 hover:border-ink-600 hover:shadow-lg hover:shadow-black/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 motion-safe:hover:-translate-y-0.5"
    :class="
      layout === 'list'
        ? 'flex flex-wrap items-center justify-between gap-x-10 gap-y-4 px-5 py-4'
        : 'p-5'
    "
    role="button"
    tabindex="0"
    @click="emit('open', server.id)"
    @keydown.enter="emit('open', server.id)"
    @keydown.space.prevent="emit('open', server.id)"
  >
    <!-- Soft colour glow in the top-left, tinted by status -->
    <span
      aria-hidden="true"
      class="pointer-events-none absolute inset-0 bg-radial-[at_0%_0%] to-transparent to-60%"
      :class="tone.glow"
    ></span>
    <!-- Subtle status line along the top edge -->
    <span
      aria-hidden="true"
      class="pointer-events-none absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent to-transparent"
      :class="tone.line"
    ></span>

    <div class="min-w-0" :class="layout === 'list' ? 'flex-1 basis-72' : ''">
      <div class="flex items-center justify-between gap-3">
        <div class="flex min-w-0 items-center gap-2">
          <h3
            class="truncate text-[17px] font-semibold tracking-tight"
            :class="server.status === 'offline' ? 'text-ink-300' : 'text-ink-100'"
          >
            {{ server.name }}
          </h3>
          <span
            v-if="demo"
            class="shrink-0 rounded-md bg-ink-700/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-ink-300"
          >
            {{ t("common.demo") }}
          </span>
        </div>
        <span
          class="inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset"
          :class="[tone.text, tone.pill]"
        >
          <span class="relative flex h-1.5 w-1.5">
            <span
              v-if="server.status !== 'offline'"
              class="absolute inline-flex h-full w-full rounded-full opacity-60 motion-safe:animate-ping"
              :class="[tone.dot, server.status === 'running' ? 'motion-safe:[animation-duration:2.4s]' : '']"
            ></span>
            <span class="relative inline-flex h-1.5 w-1.5 rounded-full" :class="tone.dot"></span>
          </span>
          {{ t(`servers.status.${server.status}`) }}
        </span>
      </div>

      <button
        type="button"
        class="group/addr mt-3 flex w-full items-center justify-between gap-3 rounded-lg border border-ink-700/70 bg-ink-950/60 px-3 py-2 text-left transition hover:border-ink-600 hover:bg-ink-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
        :title="t('servers.connectWith')"
        :aria-label="`${t('servers.connectWith')}: ${server.address}`"
        @click.stop="copyAddress"
      >
        <span class="min-w-0 truncate font-mono text-[13px] text-ink-200">{{ server.address }}</span>
        <span
          class="inline-flex shrink-0 items-center gap-1 text-xs transition"
          :class="copied ? 'text-accent-400' : 'text-ink-400 group-hover/addr:text-ink-100'"
          aria-live="polite"
        >
          <svg
            v-if="copied"
            viewBox="0 0 24 24"
            class="h-3.5 w-3.5"
            fill="none"
            stroke="currentColor"
            stroke-width="2.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
          <svg
            v-else
            viewBox="0 0 24 24"
            class="h-3.5 w-3.5"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="9" y="9" width="11" height="11" rx="2" />
            <path d="M5 15V6a2 2 0 0 1 2-2h9" />
          </svg>
          <span v-if="copied">{{ t("servers.copied") }}</span>
        </span>
      </button>
    </div>

    <div
      :class="
        layout === 'list'
          ? 'grid w-full grid-cols-3 gap-5 sm:w-[24rem] sm:flex-none'
          : 'mt-4 grid grid-cols-3 gap-4'
      "
    >
      <div v-for="stat in stats" :key="stat.key" class="min-w-0">
        <span class="inline-flex max-w-full items-center gap-1.5 text-xs text-ink-400">
          <svg
            viewBox="0 0 24 24"
            class="h-3.5 w-3.5 shrink-0"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path :d="stat.icon" />
          </svg>
          <span class="truncate">{{ stat.label }}</span>
        </span>
        <p
          class="mt-1 truncate font-mono text-[13px] font-semibold tabular-nums"
          :class="server.status === 'offline' ? 'text-ink-400' : 'text-ink-100'"
        >
          {{ stat.value }}
        </p>
        <div class="mt-1.5 h-1 overflow-hidden rounded-full bg-ink-950/80">
          <div
            v-if="stat.pct !== undefined"
            class="h-full rounded-full transition-[width,background-color] duration-700 ease-out"
            :class="barColor(stat.pct)"
            :style="{ width: `${Math.min(100, Math.max(0, stat.pct))}%` }"
          ></div>
        </div>
      </div>
    </div>
  </div>
</template>
