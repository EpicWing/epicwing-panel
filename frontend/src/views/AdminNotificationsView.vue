<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import MailSettingsPanel from "../components/MailSettingsPanel.vue";

interface NotifySettings {
  discord_enabled: boolean;
  discord_webhook_set: boolean;
  email_enabled: boolean;
  email_to: string;
  email_configured: boolean;
}

interface TestResult {
  ok: boolean;
  detail: string;
}

type Channel = "discord" | "email";

const { t } = useI18n();
const loading = ref(true);
const saving = ref(false);
const testing = ref<Channel | null>(null);
const error = ref("");
const notice = ref("");
const webhookSet = ref(false);
const emailConfigured = ref(false);
const results = reactive<Record<Channel, TestResult | null>>({ discord: null, email: null });

const form = reactive({
  discord_enabled: false,
  discord_webhook: "",
  email_enabled: false,
  email_to: "",
});

const fieldCls =
  "mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ink-400";
const labelCls = "block text-sm font-medium";
const hintCls = "mt-1 text-xs text-ink-400";
const buttonCls =
  "rounded-md border border-ink-700 px-4 py-2 text-sm font-medium hover:bg-ink-800 disabled:opacity-50";

function apply(data: NotifySettings) {
  form.discord_enabled = data.discord_enabled;
  form.discord_webhook = "";
  form.email_enabled = data.email_enabled;
  form.email_to = data.email_to;
  webhookSet.value = data.discord_webhook_set;
  emailConfigured.value = data.email_configured;
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

async function load() {
  try {
    apply(await api<NotifySettings>("/admin/notifications"));
    error.value = "";
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}

async function put(webhook: string | null) {
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    apply(
      await api<NotifySettings>("/admin/notifications", {
        method: "PUT",
        body: {
          discord_enabled: form.discord_enabled,
          discord_webhook: webhook,
          email_enabled: form.email_enabled,
          email_to: form.email_to.trim(),
        },
      }),
    );
    notice.value = t("notify.saved");
  } catch (e) {
    error.value = message(e);
  } finally {
    saving.value = false;
  }
}

function save() {
  return put(form.discord_webhook.trim() || null);
}

function removeWebhook() {
  form.discord_enabled = false;
  return put("");
}

async function runTest(channel: Channel) {
  testing.value = channel;
  results[channel] = null;
  error.value = "";
  try {
    results[channel] = await api<TestResult>("/admin/notifications/test", {
      method: "POST",
      body: { channel },
    });
  } catch (e) {
    error.value = message(e);
  } finally {
    testing.value = null;
  }
}

onMounted(() => void load());
</script>

<template>
  <AppLayout area="admin" :title="t('notify.title')" :subtitle="t('notify.subtitle')">
    <p v-if="error" role="alert" class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="notice" role="status" class="mb-6 rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm">
      {{ notice }}
    </p>
    <p v-if="loading" class="text-sm text-ink-400">…</p>

    <div v-else class="grid max-w-6xl items-start gap-6 xl:grid-cols-2">
      <form class="space-y-6 rounded-xl border border-ink-700 bg-ink-900 p-6" @submit.prevent="save">
        <div>
          <h3 class="text-base font-semibold">{{ t("notify.alertsTitle") }}</h3>
          <p class="mt-1 text-sm text-ink-400">{{ t("notify.intro") }}</p>
        </div>

        <div class="space-y-4 border-t border-ink-700 pt-5">
          <h4 class="text-sm font-semibold">{{ t("notify.discordTitle") }}</h4>
          <label class="flex items-center gap-2 text-sm">
            <input v-model="form.discord_enabled" type="checkbox" />
            {{ t("notify.discordEnable") }}
          </label>
          <div>
            <label :class="labelCls" for="nt-webhook">{{ t("notify.discordUrl") }}</label>
            <input
              id="nt-webhook"
              v-model="form.discord_webhook"
              type="password"
              autocomplete="new-password"
              placeholder="https://discord.com/api/webhooks/…"
              :class="fieldCls"
            />
            <p :class="hintCls">
              {{ webhookSet ? t("notify.discordSaved") : t("notify.discordMissing") }}
              {{ t("notify.discordHint") }}
            </p>
          </div>
          <div class="flex flex-wrap gap-3">
            <button type="button" :class="buttonCls" :disabled="testing === 'discord' || !webhookSet" @click="runTest('discord')">
              {{ testing === "discord" ? t("notify.testing") : t("notify.test") }}
            </button>
            <button v-if="webhookSet" type="button" :class="buttonCls" :disabled="saving" @click="removeWebhook">
              {{ t("notify.discordClear") }}
            </button>
          </div>
          <p
            v-if="results.discord"
            role="status"
            class="rounded-md border px-3 py-2 text-sm"
            :class="results.discord.ok ? 'border-ink-700' : 'border-bad/40 bg-bad/10 text-bad'"
          >
            {{ results.discord.ok ? t("notify.testOk") : t("notify.testFailed", { detail: results.discord.detail }) }}
          </p>
        </div>

        <div class="space-y-4 border-t border-ink-700 pt-5">
          <h4 class="text-sm font-semibold">{{ t("notify.emailTitle") }}</h4>
          <label class="flex items-center gap-2 text-sm">
            <input v-model="form.email_enabled" type="checkbox" />
            {{ t("notify.emailEnable") }}
          </label>
          <div>
            <label :class="labelCls" for="nt-email">{{ t("notify.emailTo") }}</label>
            <input id="nt-email" v-model="form.email_to" type="text" autocomplete="email" :class="fieldCls" />
            <p :class="hintCls">{{ t("notify.emailToHint") }}</p>
            <p v-if="!emailConfigured" :class="hintCls">{{ t("notify.emailNotConfigured") }}</p>
          </div>
          <div>
            <button type="button" :class="buttonCls" :disabled="testing === 'email' || !form.email_to.trim()" @click="runTest('email')">
              {{ testing === "email" ? t("notify.testing") : t("notify.test") }}
            </button>
          </div>
          <p
            v-if="results.email"
            role="status"
            class="rounded-md border px-3 py-2 text-sm"
            :class="results.email.ok ? 'border-ink-700' : 'border-bad/40 bg-bad/10 text-bad'"
          >
            {{ results.email.ok ? t("notify.testOk") : t("notify.testFailed", { detail: results.email.detail }) }}
          </p>
        </div>

        <div class="border-t border-ink-700 pt-5">
          <button type="submit" :class="buttonCls" :disabled="saving">
            {{ saving ? t("notify.saving") : t("notify.save") }}
          </button>
          <p :class="hintCls">{{ t("notify.testHint") }}</p>
        </div>
      </form>

      <div><MailSettingsPanel /></div>
    </div>
  </AppLayout>
</template>
