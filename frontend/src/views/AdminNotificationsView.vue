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

const saved = reactive({ discordEnabled: false, emailEnabled: false, emailTo: "" });


const showDelivery = ref(false);

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
  saved.discordEnabled = data.discord_enabled;
  saved.emailEnabled = data.email_enabled;
  saved.emailTo = data.email_to;
  emailConfigured.value = data.email_configured;
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}




function discordLine(): string {
  if (!webhookSet.value) return t("notify.stDiscordMissing");
  return saved.discordEnabled ? t("notify.stDiscordActive") : t("notify.stDiscordOff");
}

function emailLine(): string {
  if (!emailConfigured.value) return t("notify.stEmailNoDelivery");
  if (!saved.emailTo) return t("notify.stEmailNoRecipient");
  if (!saved.emailEnabled) return t("notify.stEmailOff");
  return t("notify.stEmailActive", { to: saved.emailTo });
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
      body: {
        channel,
        discord_webhook: form.discord_webhook.trim() || null,
        email_to: form.email_to.trim() || null,
      },
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
    <p v-if="error" role="alert" class="mb-8 max-w-4xl rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="notice" role="status" class="mb-8 max-w-4xl rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm">
      {{ notice }}
    </p>
    <p v-if="loading" class="text-sm text-ink-400">…</p>

    <div v-else class="max-w-4xl pb-20">
      <p class="mb-14 max-w-2xl text-sm leading-6 text-ink-300">{{ t("notify.intro2") }}</p>

      <form class="space-y-14" @submit.prevent="save">
        <section class="grid gap-8 md:grid-cols-3">
          <div>
            <h2 class="text-base font-semibold">{{ t("notify.tileDiscord") }}</h2>
            <p class="mt-2 text-sm leading-6 text-ink-400">{{ discordLine() }}</p>
          </div>
          <div class="space-y-6 md:col-span-2">
            <label class="flex items-center gap-2 text-sm">
              <input v-model="form.discord_enabled" type="checkbox" />
              {{ t("notify.discordCheck") }}
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
              <p :class="hintCls">{{ t("notify.discordHint2") }}</p>
            </div>
            <div class="flex flex-wrap gap-3">
              <button type="button" :class="buttonCls" :disabled="testing === 'discord' || !(webhookSet || form.discord_webhook.trim())" @click="runTest('discord')">
                {{ testing === "discord" ? t("notify.testing") : t("notify.discordTest") }}
              </button>
              <button v-if="webhookSet" type="button" :class="buttonCls" :disabled="saving" @click="removeWebhook">
                {{ t("notify.discordRemove") }}
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
        </section>

        <section class="grid gap-8 border-t border-ink-800 pt-14 md:grid-cols-3">
          <div>
            <h2 class="text-base font-semibold">{{ t("notify.tileEmail") }}</h2>
            <p class="mt-2 text-sm leading-6 text-ink-400">{{ emailLine() }}</p>
          </div>
          <div class="space-y-6 md:col-span-2">
            <label class="flex items-center gap-2 text-sm">
              <input v-model="form.email_enabled" type="checkbox" />
              {{ t("notify.emailCheck") }}
            </label>
            <div>
              <label :class="labelCls" for="nt-email">{{ t("notify.emailTo") }}</label>
              <input id="nt-email" v-model="form.email_to" type="text" autocomplete="email" :class="fieldCls" />
            </div>
            <div>
              <button type="button" :class="buttonCls" :disabled="testing === 'email' || !form.email_to.trim()" @click="runTest('email')">
                {{ testing === "email" ? t("notify.testing") : t("notify.emailTestBtn") }}
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
        </section>

        <div class="flex items-center gap-4 border-t border-ink-800 pt-10">
          <button
            type="submit"
            class="rounded-md bg-accent-500 px-5 py-2 text-sm font-semibold text-black hover:bg-accent-400 disabled:opacity-50"
            :disabled="saving"
          >
            {{ saving ? t("notify.saving") : t("notify.saveChanges") }}
          </button>
          <p class="text-xs text-ink-400">{{ t("notify.saveNote") }}</p>
        </div>
      </form>

      <section class="mt-14 grid gap-8 border-t border-ink-800 pt-14 md:grid-cols-3">
        <div>
          <h2 class="text-base font-semibold">{{ t("notify.deliveryTitle") }}</h2>
          <p class="mt-2 text-sm leading-6 text-ink-400">{{ t("notify.deliveryLead") }}</p>
        </div>
        <div class="space-y-6 md:col-span-2">
          <div>
            <button type="button" :class="buttonCls" @click="showDelivery = !showDelivery">
              {{ showDelivery ? t("notify.deliveryClose") : t("notify.deliveryOpen") }}
            </button>
          </div>
          <MailSettingsPanel v-if="showDelivery" />
        </div>
      </section>
    </div>
  </AppLayout>
</template>
