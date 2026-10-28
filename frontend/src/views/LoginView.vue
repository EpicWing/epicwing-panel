<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { auth } from "../stores/auth";

const router = useRouter();
const email = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);

async function submit() {
  error.value = "";
  busy.value = true;
  try {
    await auth.login(email.value, password.value);
    await router.push({ name: "dashboard" });
  } catch (e) {
    password.value = "";
    error.value = e instanceof ApiError ? e.message : "Der Server ist nicht erreichbar.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center px-4">
    <div class="w-full max-w-sm">
      <div class="mb-8 text-center">
        <div
          class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-indigo-500 text-xl font-bold"
        >
          F
        </div>
        <h1 class="text-2xl font-semibold tracking-tight">Forge</h1>
        <p class="mt-1 text-sm text-slate-400">Bei deinem Panel anmelden</p>
      </div>

      <form
        class="space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-6 shadow-xl"
        @submit.prevent="submit"
      >
        <div>
          <label for="email" class="mb-1 block text-sm text-slate-300">E-Mail</label>
          <input
            id="email"
            v-model="email"
            type="email"
            autocomplete="username"
            required
            class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          />
        </div>
        <div>
          <label for="password" class="mb-1 block text-sm text-slate-300">Passwort</label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-indigo-500"
          />
        </div>

        <p
          v-if="error"
          role="alert"
          class="rounded-lg border border-red-900 bg-red-950 px-3 py-2 text-sm text-red-300"
        >
          {{ error }}
        </p>

        <button
          type="submit"
          :disabled="busy"
          class="w-full rounded-lg bg-indigo-500 px-3 py-2 text-sm font-medium transition hover:bg-indigo-400 disabled:opacity-60"
        >
          {{ busy ? "Anmelden …" : "Anmelden" }}
        </button>
      </form>
    </div>
  </main>
</template>
