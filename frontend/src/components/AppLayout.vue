<script setup lang="ts">
import { useRouter } from "vue-router";

import { auth } from "../stores/auth";

defineProps<{ title: string }>();

const router = useRouter();

const navigation = [
  { label: "Dashboard", to: "/" },
  { label: "Nodes", to: "/nodes" },
  { label: "Projekte", to: null },
  { label: "Benutzer", to: null },
];

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
          E
        </div>
        <span class="text-lg font-semibold tracking-tight">EpicWing</span>
      </div>
      <nav class="space-y-1 text-sm">
        <template v-for="item in navigation" :key="item.label">
          <RouterLink
            v-if="item.to"
            :to="item.to"
            class="block rounded-lg px-3 py-2 text-slate-300 transition hover:bg-slate-800/60"
            exact-active-class="!bg-slate-800 !text-white"
          >
            {{ item.label }}
          </RouterLink>
          <div
            v-else
            class="flex cursor-not-allowed items-center justify-between rounded-lg px-3 py-2 text-slate-500"
          >
            <span>{{ item.label }}</span>
            <span class="text-[10px] uppercase tracking-wide">bald</span>
          </div>
        </template>
      </nav>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="flex items-center justify-between border-b border-slate-800 px-6 py-4">
        <h1 class="text-lg font-semibold">{{ title }}</h1>
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
        <slot />
      </main>
    </div>
  </div>
</template>
