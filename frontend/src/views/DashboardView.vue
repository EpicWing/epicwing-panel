<script setup lang="ts">
import { useRouter } from "vue-router";

import { auth } from "../stores/auth";

const router = useRouter();

const navigation = [
  { label: "Dashboard", active: true },
  { label: "Nodes", active: false },
  { label: "Projekte", active: false },
  { label: "Benutzer", active: false },
];

// Es gibt noch keine API dafür, deshalb werden bewusst keine Werte angezeigt.
const stats = ["Projekte", "Nodes", "CPU", "RAM", "Speicher", "Dienste online", "Warnungen"];

async function logout() {
  try {
    await auth.logout();
  } finally {
    await router.push({ name: "login" });
  }
}
</script>

<template>
  <div class="flex min-h-screen">
    <aside class="hidden w-56 shrink-0 flex-col border-r border-slate-800 bg-slate-900 p-4 md:flex">
      <div class="mb-8 flex items-center gap-3 px-2">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500 font-bold">
          F
        </div>
        <span class="text-lg font-semibold tracking-tight">Forge</span>
      </div>
      <nav class="space-y-1 text-sm">
        <div
          v-for="item in navigation"
          :key="item.label"
          class="flex items-center justify-between rounded-lg px-3 py-2"
          :class="item.active ? 'bg-slate-800 text-white' : 'cursor-not-allowed text-slate-500'"
        >
          <span>{{ item.label }}</span>
          <span v-if="!item.active" class="text-[10px] uppercase tracking-wide">bald</span>
        </div>
      </nav>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header
        class="flex items-center justify-between border-b border-slate-800 px-6 py-4"
      >
        <h1 class="text-lg font-semibold">Dashboard</h1>
        <div class="flex items-center gap-4 text-sm">
          <span class="hidden text-slate-400 sm:inline">{{ auth.state.user?.email }}</span>
          <button
            class="rounded-lg border border-slate-700 px-3 py-1.5 transition hover:bg-slate-800"
            @click="logout"
          >
            Abmelden
          </button>
        </div>
      </header>

      <main class="flex-1 p-6">
        <div
          class="mb-6 rounded-xl border border-amber-900/60 bg-amber-950/40 px-4 py-3 text-sm text-amber-200"
        >
          Frühe Entwicklung: Nodes, Projekte und Ressourcenanzeigen sind noch nicht implementiert.
          Die Karten unten sind Platzhalter ohne echte Daten.
        </div>

        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div
            v-for="stat in stats"
            :key="stat"
            class="rounded-xl border border-slate-800 bg-slate-900 p-5"
          >
            <p class="text-sm text-slate-400">{{ stat }}</p>
            <p class="mt-2 text-2xl font-semibold text-slate-600">–</p>
            <p class="mt-1 text-xs text-slate-500">nicht implementiert</p>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>
