<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

type Provider = "resend" | "smtp";
type Security = "starttls" | "ssl" | "none";

interface MailSettings {
  provider: Provider;
  sender: string;
  reply_to: string;
  discord_url: string;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_security: Security;
  resend_api_key_set: boolean;
  smtp_password_set: boolean;
  configured: boolean;
}

const { t } = useI18n();
const loading = ref(true);
const saving = ref(false);
const testing = ref(false);
const error = ref("");
const notice = ref("");
const keySet = ref(false);
const passwordSet = ref(false);
const configured = ref(false);
const testTo = ref("");
const testResult = ref<{ ok: boolean; detail: string } | null>(null);
const senderExample = "My Panel <noreply@example.com>";

const form = reactive({
  provider: "resend" as Provider,
  sender: "",
  reply_to: "",
  discord_url: "",
  smtp_host: "",
  smtp_port: 587,
  smtp_user: "",
  smtp_security: "starttls" as Security,
  resend_api_key: "",
  smtp_password: "",
});

const fieldCls =
  "mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ink-400";
const labelCls = "block text-sm font-medium";
const hintCls = "mt-1 text-xs text-ink-400";
const buttonCls =
  "rounded-md border border-ink-700 px-4 py-2 text-sm font-medium hover:bg-ink-800 disabled:opacity-50";

function apply(data: MailSettings) {
  form.provider = data.provider;
  form.sender = data.sender;
  form.reply_to = data.reply_to;
  form.discord_url = data.discord_url;
  form.smtp_host = data.smtp_host;
  form.smtp_port = data.smtp_port;
  form.smtp_user = data.smtp_user;
  form.smtp_security = data.smtp_security;
  form.resend_api_key = "";
  form.smtp_password = "";
  keySet.value = data.resend_api_key_set;
  passwordSet.value = data.smtp_password_set;
  configured.value = data.configured;
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

async function load() {
  try {
    apply(await api<MailSettings>("/admin/mail"));
    error.value = "";
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  error.value = "";
  notice.value = "";
  try {
    apply(
      await api<MailSettings>("/admin/mail", {
        method: "PUT",
        body: {
          provider: form.provider,
          sender: form.sender.trim(),
          reply_to: form.reply_to.trim(),
          discord_url: form.discord_url.trim(),
          smtp_host: form.smtp_host.trim(),
          smtp_port: form.smtp_port,
          smtp_user: form.smtp_user.trim(),
          smtp_security: form.smtp_security,
          resend_api_key: form.resend_api_key.trim() || null,
          smtp_password: form.smtp_password || null,
        },
      }),
    );
    notice.value = t("mail.saved");
  } catch (e) {
    error.value = message(e);
  } finally {
    saving.value = false;
  }
}

async function sendTest() {
  testing.value = true;
  testResult.value = null;
  error.value = "";
  try {
    testResult.value = await api<{ ok: boolean; detail: string }>("/admin/mail/test", {
      method: "POST",
      body: { to: testTo.value.trim() },
    });
  } catch (e) {
    error.value = message(e);
  } finally {
    testing.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <AppLayout area="admin" :title="t('mail.title')" :subtitle="t('mail.subtitle')">
    <p v-if="error" role="alert" class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="notice" role="status" class="mb-6 rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm">
      {{ notice }}
    </p>
    <p v-if="loading" class="text-sm text-ink-400">…</p>
    <div v-else class="max-w-2xl space-y-6">
      <form class="space-y-5 rounded-xl border border-ink-700 bg-ink-900 p-6" @submit.prevent="save">
        <p class="text-sm text-ink-400">
          {{ configured ? t("mail.configured") : t("mail.notConfigured") }}
        </p>
        <p class="text-xs text-ink-400">{{ t("mail.envNote") }}</p>

        <div>
          <label :class="labelCls" for="mail-provider">{{ t("mail.provider") }}</label>
          <select id="mail-provider" v-model="form.provider" :class="fieldCls">
            <option value="resend">{{ t("mail.providerResend") }}</option>
            <option value="smtp">{{ t("mail.providerSmtp") }}</option>
          </select>
        </div>

        <div>
          <label :class="labelCls" for="mail-sender">{{ t("mail.sender") }}</label>
          <input id="mail-sender" v-model="form.sender" type="text" :placeholder="senderExample" :class="fieldCls" />
          <p :class="hintCls">{{ t("mail.senderHint") }}</p>
        </div>

        <div>
          <label :class="labelCls" for="mail-reply">{{ t("mail.replyTo") }}</label>
          <input id="mail-reply" v-model="form.reply_to" type="text" :class="fieldCls" />
          <p :class="hintCls">{{ t("mail.replyToHint") }}</p>
        </div>

        <div>
          <label :class="labelCls" for="mail-discord">{{ t("mail.discord") }}</label>
          <input id="mail-discord" v-model="form.discord_url" type="text" placeholder="https://" :class="fieldCls" />
          <p :class="hintCls">{{ t("mail.discordHint") }}</p>
        </div>

        <div v-if="form.provider === 'resend'">
          <label :class="labelCls" for="mail-key">{{ t("mail.resendKey") }}</label>
          <input
            id="mail-key"
            v-model="form.resend_api_key"
            type="password"
            autocomplete="new-password"
            :class="fieldCls"
          />
          <p :class="hintCls">
            {{ keySet ? t("mail.keySaved") : t("mail.keyMissing") }} {{ t("mail.keyHint") }}
          </p>
        </div>

        <div v-else class="space-y-5">
          <div class="grid gap-5 sm:grid-cols-3">
            <div class="sm:col-span-2">
              <label :class="labelCls" for="mail-host">{{ t("mail.smtpHost") }}</label>
              <input id="mail-host" v-model="form.smtp_host" type="text" :class="fieldCls" />
            </div>
            <div>
              <label :class="labelCls" for="mail-port">{{ t("mail.smtpPort") }}</label>
              <input id="mail-port" v-model.number="form.smtp_port" type="number" min="1" max="65535" :class="fieldCls" />
            </div>
          </div>
          <div>
            <label :class="labelCls" for="mail-security">{{ t("mail.security") }}</label>
            <select id="mail-security" v-model="form.smtp_security" :class="fieldCls">
              <option value="starttls">{{ t("mail.securityStarttls") }}</option>
              <option value="ssl">{{ t("mail.securitySsl") }}</option>
              <option value="none">{{ t("mail.securityNone") }}</option>
            </select>
          </div>
          <div class="grid gap-5 sm:grid-cols-2">
            <div>
              <label :class="labelCls" for="mail-user">{{ t("mail.smtpUser") }}</label>
              <input id="mail-user" v-model="form.smtp_user" type="text" autocomplete="off" :class="fieldCls" />
            </div>
            <div>
              <label :class="labelCls" for="mail-pass">{{ t("mail.smtpPassword") }}</label>
              <input
                id="mail-pass"
                v-model="form.smtp_password"
                type="password"
                autocomplete="new-password"
                :class="fieldCls"
              />
            </div>
          </div>
          <p :class="hintCls">{{ passwordSet ? t("mail.keySaved") : t("mail.keyMissing") }} {{ t("mail.passwordHint") }}</p>
        </div>

        <button type="submit" :disabled="saving" :class="buttonCls">
          {{ saving ? t("mail.saving") : t("mail.save") }}
        </button>
      </form>

      <form class="space-y-4 rounded-xl border border-ink-700 bg-ink-900 p-6" @submit.prevent="sendTest">
        <h3 class="text-base font-semibold">{{ t("mail.testTitle") }}</h3>
        <div>
          <label :class="labelCls" for="mail-test-to">{{ t("mail.testTo") }}</label>
          <input id="mail-test-to" v-model="testTo" type="text" autocomplete="email" :class="fieldCls" />
        </div>
        <button type="submit" :disabled="testing || !testTo.trim()" :class="buttonCls">
          {{ testing ? t("mail.testing") : t("mail.testButton") }}
        </button>
        <p
          v-if="testResult"
          role="status"
          class="rounded-md border px-3 py-2 text-sm"
          :class="testResult.ok ? 'border-ink-700' : 'border-bad/40 bg-bad/10 text-bad'"
        >
          {{ testResult.ok ? t("mail.testOk") : t("mail.testFailed", { detail: testResult.detail }) }}
        </p>
      </form>
    </div>
  </AppLayout>
</template>
