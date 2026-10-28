<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";

const props = defineProps<{
  label: string;
  value: string;
  detail: string;
  points: number[];
}>();

// 60 Messpunkte im Fenster, bei 10 s Abstand sind das 10 Minuten.
const MAX_POINTS = 60;
const W = 100;
const H = 40;

const coords = computed(() => {
  const pts = props.points;
  if (pts.length < 2) {
    return [] as [number, number][];
  }
  const step = W / (MAX_POINTS - 1);
  const offset = W - (pts.length - 1) * step;
  return pts.map((v, i): [number, number] => [
    offset + i * step,
    H - (Math.min(100, Math.max(0, v)) / 100) * H,
  ]);
});

// Weiche Kurve: waagerechte Tangenten an den Messpunkten, dadurch kein Überschwingen.
const line = computed(() =>
  coords.value
    .map(([x, y], i, all) => {
      if (i === 0) return `M${x.toFixed(2)} ${y.toFixed(2)}`;
      const [px, py] = all[i - 1];
      const mx = ((px + x) / 2).toFixed(2);
      return `C${mx} ${py.toFixed(2)} ${mx} ${y.toFixed(2)} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" "),
);

const area = computed(() => {
  const c = coords.value;
  if (c.length === 0) {
    return "";
  }
  const first = c[0];
  const last = c[c.length - 1];
  return `${line.value} L${last[0].toFixed(2)} ${H} L${first[0].toFixed(2)} ${H} Z`;
});

const gradientId = `fill-${Math.random().toString(36).slice(2, 9)}`;

// Bei einem neuen Messpunkt startet die Linie einen Schritt weiter rechts und gleitet zurück.
const STEP = W / (MAX_POINTS - 1);
const glide = ref<SVGGElement | null>(null);
const shift = ref(0);
const gliding = ref(false);

watch(
  () => props.points,
  async () => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    gliding.value = false;
    shift.value = STEP;
    await nextTick();
    glide.value?.getBoundingClientRect(); // Startzustand übernehmen, sonst entfällt die Transition
    gliding.value = true;
    shift.value = 0;
  },
  { deep: true },
);
</script>

<template>
  <div class="overflow-hidden rounded-lg border border-ink-700 bg-ink-900">
    <div class="flex items-start justify-between px-5 pt-4">
      <div>
        <p class="text-xs font-medium uppercase tracking-wider text-ink-400">{{ label }}</p>
        <p class="mt-1 text-3xl font-semibold tracking-tight">{{ value }}</p>
      </div>
      <p class="mt-1 text-right font-mono text-xs text-ink-300">{{ detail }}</p>
    </div>
    <svg
      class="mt-3 block h-28 w-full text-accent-500"
      :viewBox="`0 0 ${W} ${H}`"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="currentColor" stop-opacity="0.35" />
          <stop offset="100%" stop-color="currentColor" stop-opacity="0" />
        </linearGradient>
      </defs>
      <line
        v-for="y in [10, 20, 30]"
        :key="y"
        x1="0"
        :y1="y"
        :x2="W"
        :y2="y"
        stroke="var(--color-ink-700)"
        stroke-width="1"
        vector-effect="non-scaling-stroke"
      />
      <g
        ref="glide"
        :style="{
          transform: `translateX(${shift}px)`,
          transition: gliding ? 'transform 700ms cubic-bezier(0.22, 1, 0.36, 1)' : 'none',
        }"
      >
        <path v-if="area" :d="area" :fill="`url(#${gradientId})`" />
        <path
          v-if="line"
          :d="line"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linejoin="round"
          vector-effect="non-scaling-stroke"
        />
      </g>
    </svg>
  </div>
</template>
