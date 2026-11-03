<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { api, ApiError } from "../api/client";
import LogoMark from "../components/LogoMark.vue";

const { t } = useI18n();
const token = ref("");
const email = ref("");
const password = ref("");
const repeat = ref("");
const error = ref("");
const notice = ref("");
const done = ref(false);
const busy = ref(false);

onMounted(() => {
  // The token sits behind the # in the link. It is read once and removed from the address bar.
  const found = new URLSearchParams(window.location.hash.slice(1)).get("token");
  if (found) {
    token.value = found;
    window.history.replaceState(window.history.state, "", window.location.pathname);
  }
});

async function requestLink() {
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    await api<{ detail: string }>("/auth/password-reset/request", {
      method: "POST",
      body: { email: email.value },
    });
    notice.value = t("reset.sent");
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t("common.unreachable");
  } finally {
    busy.value = false;
  }
}

async function savePassword() {
  error.value = "";
  if (password.value.length < 8) {
    error.value = t("reset.tooShort");
    return;
  }
  if (password.value !== repeat.value) {
    error.value = t("reset.mismatch");
    return;
  }
  busy.value = true;
  try {
    await api<void>("/auth/password-reset/confirm", {
      method: "POST",
      body: { token: token.value, new_password: password.value },
    });
    password.value = "";
    repeat.value = "";
    done.value = true;
  } catch (e) {
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
          <h1 class="text-xl font-semibold leading-tight tracking-tight">
            {{ token && !done ? t("reset.newTitle") : t("reset.title") }}
          </h1>
          <p class="text-sm text-ink-400">EpicWing</p>
        </div>
      </div>

      <div
        v-if="done"
        class="space-y-4 rounded-lg border border-ink-700 bg-ink-900 p-6"
      >
        <p class="text-sm text-ink-300">{{ t("reset.done") }}</p>
        <router-link
          :to="{ name: 'login' }"
          class="block w-full rounded-md bg-accent-500 px-3 py-2 text-center text-sm font-semibold text-ink-950 transition hover:bg-accent-400"
        >
          {{ t("reset.toLogin") }}
        </router-link>
      </div>

      <form
        v-else-if="token"
        class="space-y-4 rounded-lg border border-ink-700 bg-ink-900 p-6"
        @submit.prevent="savePassword"
      >
        <div>
          <label for="new-password" class="mb-1.5 block text-sm text-ink-300">
            {{ t("reset.newPassword") }}
          </label>
          <input
            id="new-password"
            v-model="password"
            type="password"
            autocomplete="new-password"
            minlength="8"
            required
            class="w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500"
          />
        </div>
        <div>
          <label for="repeat-password" class="mb-1.5 block text-sm text-ink-300">
            {{ t("reset.repeat") }}
          </label>
          <input
            id="repeat-password"
            v-model="repeat"
            type="password"
            autocomplete="new-password"
            minlength="8"
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
          {{ busy ? t("reset.saving") : t("reset.save") }}
        </button>
      </form>

      <form
        v-else
        class="space-y-4 rounded-lg border border-ink-700 bg-ink-900 p-6"
        @submit.prevent="requestLink"
      >
        <p class="text-sm text-ink-400">{{ t("reset.requestHint") }}</p>
        <div>
          <label for="reset-email" class="mb-1.5 block text-sm text-ink-300">
            {{ t("reset.email") }}
          </label>
          <input
            id="reset-email"
            v-model="email"
            type="email"
            autocomplete="username"
            required
            class="w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500"
          />
        </div>
        <p
          v-if="notice"
          role="status"
          class="rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-300"
        >
          {{ notice }}
        </p>
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
          {{ busy ? t("reset.sending") : t("reset.send") }}
        </button>
        <router-link
          :to="{ name: 'login' }"
          class="block w-full text-center text-sm text-ink-400 transition hover:text-ink-200"
        >
          {{ t("reset.toLogin") }}
        </router-link>
      </form>
    </div>
  </main>
</template>
