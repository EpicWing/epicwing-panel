<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { ApiError } from "../api/client";
import LogoMark from "../components/LogoMark.vue";
import { auth } from "../stores/auth";

const { t } = useI18n();
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
    await router.push({ name: "servers" });
  } catch (e) {
    password.value = "";
    error.value = e instanceof ApiError ? e.message : t("common.unreachable");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <main class="flex min-h-screen items-center justify-center px-4">
    <div class="w-full max-w-sm">
      <div class="mb-6 flex items-center gap-3">
        <LogoMark class="h-8 w-8 text-accent-500" />
        <div>
          <h1 class="text-xl font-semibold leading-tight tracking-tight">EpicWing</h1>
          <p class="text-sm text-ink-400">{{ t("login.subtitle") }}</p>
        </div>
      </div>

      <form
        class="space-y-4 rounded-lg border border-ink-700 bg-ink-900 p-6"
        @submit.prevent="submit"
      >
        <div>
          <label for="email" class="mb-1.5 block text-sm text-ink-300">{{ t("login.email") }}</label>
          <input
            id="email"
            v-model="email"
            type="email"
            autocomplete="username"
            required
            class="w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500"
          />
        </div>
        <div>
          <label for="password" class="mb-1.5 block text-sm text-ink-300">
            {{ t("login.password") }}
          </label>
          <input
            id="password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            class="w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500"
          />
        </div>

        <p
          v-if="error"
          role="alert"
          class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
        >
          {{ error }}
        </p>

        <button
          type="submit"
          :disabled="busy"
          class="w-full rounded-md bg-accent-500 px-3 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60"
        >
          {{ busy ? t("login.submitting") : t("login.submit") }}
        </button>
      </form>

      <p class="mt-4 text-center text-xs text-ink-400">{{ t("login.notice") }}</p>
    </div>
  </main>
</template>
