<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";

interface TwoFactorStatus {
  enabled: boolean;
  recovery_codes_remaining: number;
}

interface SetupData {
  secret: string;
  otpauth_uri: string;
  qr_svg: string;
}

interface CodesData {
  recovery_codes: string[];
}

type Mode = "idle" | "password" | "scan" | "codes" | "regenerate" | "disable";

const { t } = useI18n();

const status = ref<TwoFactorStatus | null>(null);
const loadFailed = ref(false);
const mode = ref<Mode>("idle");
const password = ref("");
const code = ref("");
const setup = ref<SetupData | null>(null);
const codes = ref<string[]>([]);
const error = ref("");
const busy = ref(false);
const copied = ref(false);

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const primaryClass =
  "rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const secondaryClass =
  "rounded-md border border-ink-700 px-4 py-2 text-sm text-ink-300 transition hover:border-accent-500 disabled:opacity-60";
const dangerClass =
  "rounded-md border border-bad/40 px-4 py-2 text-sm text-bad transition hover:bg-bad/10 disabled:opacity-60";

// An SVG inside <img> can never run scripts.
const qrSrc = computed(() =>
  setup.value ? `data:image/svg+xml;utf8,${encodeURIComponent(setup.value.qr_svg)}` : "",
);

async function load() {
  try {
    status.value = await api<TwoFactorStatus>("/auth/2fa");
    loadFailed.value = false;
  } catch {
    loadFailed.value = true;
  }
}

// Leaving a view wipes everything secret from memory.
function leave() {
  mode.value = "idle";
  password.value = "";
  code.value = "";
  error.value = "";
  setup.value = null;
  codes.value = [];
  copied.value = false;
}

async function run(action: () => Promise<void>) {
  error.value = "";
  busy.value = true;
  try {
    await action();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t("common.unreachable");
  } finally {
    busy.value = false;
  }
}

function startSetup() {
  return run(async () => {
    setup.value = await api<SetupData>("/auth/2fa/setup", {
      method: "POST",
      body: { password: password.value },
    });
    password.value = "";
    code.value = "";
    mode.value = "scan";
  });
}

function enable() {
  return run(async () => {
    const data = await api<CodesData>("/auth/2fa/enable", {
      method: "POST",
      body: { code: code.value },
    });
    codes.value = data.recovery_codes;
    setup.value = null;
    code.value = "";
    mode.value = "codes";
    await load();
  });
}

function regenerate() {
  return run(async () => {
    const data = await api<CodesData>("/auth/2fa/recovery-codes", {
      method: "POST",
      body: { password: password.value, code: code.value },
    });
    codes.value = data.recovery_codes;
    password.value = "";
    code.value = "";
    mode.value = "codes";
    await load();
  });
}

function disable() {
  return run(async () => {
    await api<void>("/auth/2fa/disable", {
      method: "POST",
      body: { password: password.value, code: code.value },
    });
    leave();
    await load();
  });
}

async function copyCodes() {
  try {
    await navigator.clipboard.writeText(codes.value.join("\n"));
    copied.value = true;
  } catch {
    copied.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="max-w-lg rounded-xl border border-ink-700 bg-ink-900 p-6">
    <h2 class="text-lg font-semibold">{{ t("twoFactor.title") }}</h2>
    <p class="mt-1 text-sm text-ink-400">{{ t("twoFactor.body") }}</p>

    <p
      v-if="loadFailed"
      role="alert"
      class="mt-4 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
    >
      {{ t("common.unreachable") }}
    </p>

    <div v-else-if="status" class="mt-5 space-y-4">
      <p
        v-if="error"
        role="alert"
        class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
      >
        {{ error }}
      </p>

      <div v-if="mode === 'idle'" class="space-y-3">
        <p class="text-sm">
          <span :class="status.enabled ? 'font-semibold text-ok' : 'text-ink-300'">
            {{ status.enabled ? t("twoFactor.on") : t("twoFactor.off") }}
          </span>
        </p>
        <template v-if="status.enabled">
          <p class="text-sm text-ink-400">
            {{ t("twoFactor.remaining", { count: status.recovery_codes_remaining }) }}
          </p>
          <p
            v-if="status.recovery_codes_remaining <= 3"
            role="alert"
            class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
          >
            {{ t("twoFactor.lowCodes") }}
          </p>
          <div class="flex flex-wrap gap-3">
            <button type="button" :class="secondaryClass" @click="mode = 'regenerate'">
              {{ t("twoFactor.regenerate") }}
            </button>
            <button type="button" :class="dangerClass" @click="mode = 'disable'">
              {{ t("twoFactor.disable") }}
            </button>
          </div>
        </template>
        <button v-else type="button" :class="primaryClass" @click="mode = 'password'">
          {{ t("twoFactor.enable") }}
        </button>
      </div>

      <form v-else-if="mode === 'password'" class="space-y-4" @submit.prevent="startSetup">
        <p class="text-sm text-ink-400">{{ t("twoFactor.passwordHint") }}</p>
        <div>
          <label for="tf-password" class="mb-1.5 block text-sm text-ink-300">
            {{ t("twoFactor.password") }}
          </label>
          <input
            id="tf-password"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            :class="inputClass"
          />
        </div>
        <div class="flex gap-3">
          <button type="submit" :disabled="busy" :class="primaryClass">
            {{ t("twoFactor.continue") }}
          </button>
          <button type="button" :class="secondaryClass" @click="leave">
            {{ t("twoFactor.cancel") }}
          </button>
        </div>
      </form>

      <form v-else-if="mode === 'scan' && setup" class="space-y-4" @submit.prevent="enable">
        <h3 class="text-base font-semibold">{{ t("twoFactor.scanTitle") }}</h3>
        <p class="text-sm text-ink-400">{{ t("twoFactor.scanBody") }}</p>
        <img :src="qrSrc" :alt="t('twoFactor.qrAlt')" class="h-48 w-48 rounded-md bg-white p-2" />
        <div>
          <p class="text-sm text-ink-300">{{ t("twoFactor.manualKey") }}</p>
          <code
            class="mt-1 block break-all rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-sm"
          >
            {{ setup.secret }}
          </code>
        </div>
        <div>
          <label for="tf-code" class="mb-1.5 block text-sm text-ink-300">
            {{ t("twoFactor.codeApp") }}
          </label>
          <input
            id="tf-code"
            v-model="code"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            maxlength="7"
            required
            :class="inputClass"
          />
        </div>
        <div class="flex gap-3">
          <button type="submit" :disabled="busy" :class="primaryClass">
            {{ t("twoFactor.confirm") }}
          </button>
          <button type="button" :class="secondaryClass" @click="leave">
            {{ t("twoFactor.cancel") }}
          </button>
        </div>
      </form>

      <div v-else-if="mode === 'codes'" class="space-y-4">
        <h3 class="text-base font-semibold">{{ t("twoFactor.codesTitle") }}</h3>
        <p class="text-sm text-ink-400">{{ t("twoFactor.codesBody") }}</p>
        <ul
          class="grid grid-cols-2 gap-2 rounded-md border border-ink-700 bg-ink-950 p-4 font-mono text-sm"
        >
          <li v-for="item in codes" :key="item">{{ item }}</li>
        </ul>
        <div class="flex flex-wrap gap-3">
          <button type="button" :class="secondaryClass" @click="copyCodes">
            {{ copied ? t("twoFactor.copied") : t("twoFactor.copy") }}
          </button>
          <button type="button" :class="primaryClass" @click="leave">
            {{ t("twoFactor.done") }}
          </button>
        </div>
      </div>

      <form
        v-else-if="mode === 'regenerate' || mode === 'disable'"
        class="space-y-4"
        @submit.prevent="mode === 'disable' ? disable() : regenerate()"
      >
        <h3 class="text-base font-semibold">
          {{ mode === "disable" ? t("twoFactor.disableTitle") : t("twoFactor.regenerateTitle") }}
        </h3>
        <p class="text-sm text-ink-400">
          {{ mode === "disable" ? t("twoFactor.disableBody") : t("twoFactor.regenerateBody") }}
        </p>
        <div>
          <label for="tf-password2" class="mb-1.5 block text-sm text-ink-300">
            {{ t("twoFactor.password") }}
          </label>
          <input
            id="tf-password2"
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            :class="inputClass"
          />
        </div>
        <div>
          <label for="tf-code2" class="mb-1.5 block text-sm text-ink-300">
            {{ mode === "disable" ? t("twoFactor.codeOrRecovery") : t("twoFactor.codeApp") }}
          </label>
          <input
            id="tf-code2"
            v-model="code"
            type="text"
            autocomplete="one-time-code"
            maxlength="32"
            required
            :class="inputClass"
          />
        </div>
        <div class="flex gap-3">
          <button
            type="submit"
            :disabled="busy"
            :class="mode === 'disable' ? dangerClass : primaryClass"
          >
            {{ mode === "disable" ? t("twoFactor.disable") : t("twoFactor.regenerate") }}
          </button>
          <button type="button" :class="secondaryClass" @click="leave">
            {{ t("twoFactor.cancel") }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>
