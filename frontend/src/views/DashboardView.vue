<script setup lang="ts">
import { onMounted, ref } from "vue";

import { api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

const nodeCount = ref<number | null>(null);

// Es gibt noch keine API dafür, deshalb werden bewusst keine Werte angezeigt.
const placeholders = ["Projekte", "CPU", "RAM", "Speicher", "Dienste online", "Warnungen"];

onMounted(async () => {
  try {
    nodeCount.value = (await api<unknown[]>("/nodes")).length;
  } catch {
    // Ohne Berechtigung oder bei einem Fehler bleibt die Karte leer.
  }
});
</script>

<template>
  <AppLayout title="Dashboard">
    <div
      class="mb-6 rounded-xl border border-amber-900/60 bg-amber-950/40 px-4 py-3 text-sm text-amber-200"
    >
      Frühe Entwicklung: Projekte, Agent und Ressourcenanzeigen sind noch nicht implementiert.
      Karten mit „nicht implementiert“ sind Platzhalter ohne echte Daten.
    </div>

    <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div class="rounded-xl border border-slate-800 bg-slate-900 p-5">
        <p class="text-sm text-slate-400">Nodes</p>
        <p class="mt-2 text-2xl font-semibold" :class="nodeCount === null ? 'text-slate-600' : ''">
          {{ nodeCount ?? "–" }}
        </p>
        <p class="mt-1 text-xs text-slate-500">angelegt, Online-Status folgt mit dem Agent</p>
      </div>

      <div
        v-for="stat in placeholders"
        :key="stat"
        class="rounded-xl border border-slate-800 bg-slate-900 p-5"
      >
        <p class="text-sm text-slate-400">{{ stat }}</p>
        <p class="mt-2 text-2xl font-semibold text-slate-600">–</p>
        <p class="mt-1 text-xs text-slate-500">nicht implementiert</p>
      </div>
    </div>
  </AppLayout>
</template>
