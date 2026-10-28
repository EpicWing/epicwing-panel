<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

interface HostRow {
  id: string;
  name: string;
  host: string;
  port: number;
  admin_user: string;
  max_databases: number | null;
  database_count: number;
  created_at: string;
}

interface TestResult {
  ok: boolean;
  message: string;
}

const { t } = useI18n();
const rows = ref<HostRow[]>([]);
const loading = ref(true);
const saving = ref(false);
const error = ref("");
const notice = ref("");
const editing = ref<string | null>(null);
const testing = ref<string | null>(null);
const results = ref<Record<string, TestResult>>({});

const form = reactive({
  name: "",
  host: "",
  port: 3306,
  admin_user: "",
  admin_password: "",
  max_databases: "" as number | "",
});

const fieldCls =
  "mt-1 w-full rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ink-400";
const labelCls = "block text-sm font-medium";
const hintCls = "mt-1 text-xs text-ink-400";
const buttonCls =
  "rounded-md border border-ink-700 px-3 py-1.5 text-sm font-medium hover:bg-ink-800 disabled:opacity-50";
const primaryCls =
  "rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-50";
const dangerCls =
  "rounded-md border border-bad/50 px-3 py-1.5 text-sm text-bad hover:bg-bad/10 disabled:opacity-50";

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

function usage(row: HostRow): string {
  return row.max_databases === null
    ? String(row.database_count)
    : `${row.database_count} / ${row.max_databases}`;
}

async function load() {
  try {
    rows.value = await api<HostRow[]>("/admin/database-hosts");
    error.value = "";
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}

function startNew() {
  Object.assign(form, {
    name: "",
    host: "172.17.0.1",
    port: 3306,
    admin_user: "",
    admin_password: "",
    max_databases: "",
  });
  notice.value = "";
  editing.value = "new";
}

function startEdit(row: HostRow) {
  Object.assign(form, {
    name: row.name,
    host: row.host,
    port: row.port,
    admin_user: row.admin_user,
    admin_password: "",
    max_databases: row.max_databases ?? "",
  });
  notice.value = "";
  editing.value = row.id;
}

async function save() {
  saving.value = true;
  error.value = "";
  notice.value = "";
  const max = form.max_databases === "" ? null : Number(form.max_databases);
  try {
    if (editing.value === "new") {
      await api("/admin/database-hosts", {
        method: "POST",
        body: {
          name: form.name.trim(),
          host: form.host.trim(),
          port: form.port,
          admin_user: form.admin_user.trim(),
          admin_password: form.admin_password,
          max_databases: max,
        },
      });
    } else {
      const row = rows.value.find((entry) => entry.id === editing.value);
      const body: Record<string, unknown> = {};
      if (row) {
        if (form.name.trim() !== row.name) body.name = form.name.trim();
        if (form.host.trim() !== row.host) body.host = form.host.trim();
        if (form.port !== row.port) body.port = form.port;
        if (form.admin_user.trim() !== row.admin_user) body.admin_user = form.admin_user.trim();
        if (max !== row.max_databases) body.max_databases = max;
      }
      if (form.admin_password) body.admin_password = form.admin_password;
      await api(`/admin/database-hosts/${editing.value}`, { method: "PATCH", body });
    }
    editing.value = null;
    notice.value = t("databaseHosts.saved");
    await load();
  } catch (e) {
    error.value = message(e);
  } finally {
    saving.value = false;
  }
}

async function test(row: HostRow) {
  testing.value = row.id;
  error.value = "";
  try {
    const result = await api<TestResult>(`/admin/database-hosts/${row.id}/test`, {
      method: "POST",
    });
    results.value = { ...results.value, [row.id]: result };
  } catch (e) {
    error.value = message(e);
  } finally {
    testing.value = null;
  }
}

async function remove(row: HostRow) {
  if (!window.confirm(t("databaseHosts.confirmDelete"))) return;
  error.value = "";
  notice.value = "";
  try {
    await api(`/admin/database-hosts/${row.id}`, { method: "DELETE" });
    notice.value = t("databaseHosts.deleted");
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

onMounted(() => void load());
</script>

<template>
  <AppLayout area="admin" :title="t('databaseHosts.title')" :subtitle="t('databaseHosts.subtitle')">
    <p v-if="error" role="alert" class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="notice" role="status" class="mb-6 rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm">
      {{ notice }}
    </p>
    <p v-if="loading" class="text-sm text-ink-400">…</p>

    <div v-else class="space-y-6">
      <form v-if="editing" class="max-w-3xl space-y-5 rounded-xl border border-ink-700 bg-ink-900 p-6" @submit.prevent="save">
        <h3 class="text-base font-semibold">
          {{ editing === "new" ? t("databaseHosts.createTitle") : t("databaseHosts.editTitle") }}
        </h3>
        <div>
          <label :class="labelCls" for="dbh-name">{{ t("databaseHosts.name") }}</label>
          <input id="dbh-name" v-model="form.name" type="text" maxlength="64" :class="fieldCls" />
        </div>
        <div class="grid gap-5 sm:grid-cols-3">
          <div class="sm:col-span-2">
            <label :class="labelCls" for="dbh-host">{{ t("databaseHosts.host") }}</label>
            <input id="dbh-host" v-model="form.host" type="text" :class="fieldCls" />
            <p :class="hintCls">{{ t("databaseHosts.hostHint") }}</p>
          </div>
          <div>
            <label :class="labelCls" for="dbh-port">{{ t("databaseHosts.port") }}</label>
            <input id="dbh-port" v-model.number="form.port" type="number" min="1" max="65535" :class="fieldCls" />
          </div>
        </div>
        <div class="grid gap-5 sm:grid-cols-2">
          <div>
            <label :class="labelCls" for="dbh-user">{{ t("databaseHosts.adminUser") }}</label>
            <input id="dbh-user" v-model="form.admin_user" type="text" autocomplete="off" :class="fieldCls" />
          </div>
          <div>
            <label :class="labelCls" for="dbh-pass">{{ t("databaseHosts.adminPassword") }}</label>
            <input id="dbh-pass" v-model="form.admin_password" type="password" autocomplete="new-password" :class="fieldCls" />
            <p v-if="editing !== 'new'" :class="hintCls">{{ t("databaseHosts.passwordKeep") }}</p>
          </div>
        </div>
        <div>
          <label :class="labelCls" for="dbh-max">{{ t("databaseHosts.maxDatabases") }}</label>
          <input id="dbh-max" v-model.number="form.max_databases" type="number" min="1" :class="fieldCls" />
          <p :class="hintCls">{{ t("databaseHosts.maxHint") }}</p>
        </div>
        <div class="flex gap-3">
          <button type="submit" :class="primaryCls" :disabled="saving">
            {{ saving ? t("databaseHosts.saving") : t("databaseHosts.save") }}
          </button>
          <button type="button" :class="buttonCls" @click="editing = null">{{ t("databaseHosts.cancel") }}</button>
        </div>
      </form>

      <section class="overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
        <div class="flex items-center justify-between border-b border-ink-700 px-4 py-3">
          <h3 class="text-base font-semibold">{{ t("databaseHosts.listTitle") }}</h3>
          <button v-if="!editing" :class="primaryCls" @click="startNew">{{ t("databaseHosts.add") }}</button>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm">
            <thead>
              <tr class="border-b border-ink-700 text-xs uppercase tracking-wide text-ink-400">
                <th class="px-4 py-3 font-semibold">{{ t("databaseHosts.colId") }}</th>
                <th class="px-4 py-3 font-semibold">{{ t("databaseHosts.name") }}</th>
                <th class="px-4 py-3 font-semibold">{{ t("databaseHosts.host") }}</th>
                <th class="px-4 py-3 font-semibold">{{ t("databaseHosts.port") }}</th>
                <th class="px-4 py-3 font-semibold">{{ t("databaseHosts.colUsername") }}</th>
                <th class="px-4 py-3 font-semibold">{{ t("databaseHosts.colDatabases") }}</th>
                <th class="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              <template v-for="row in rows" :key="row.id">
                <tr class="border-b border-ink-800 last:border-0 hover:bg-ink-800/40">
                  <td class="px-4 py-3 font-mono text-xs text-ink-400">{{ row.id.slice(0, 8) }}</td>
                  <td class="px-4 py-3 font-medium">{{ row.name }}</td>
                  <td class="px-4 py-3 font-mono">{{ row.host }}</td>
                  <td class="px-4 py-3 font-mono">{{ row.port }}</td>
                  <td class="px-4 py-3 font-mono">{{ row.admin_user }}</td>
                  <td class="px-4 py-3">{{ usage(row) }}</td>
                  <td class="px-4 py-3">
                    <div class="flex justify-end gap-2">
                      <button :class="buttonCls" :disabled="testing === row.id" @click="test(row)">
                        {{ testing === row.id ? t("databaseHosts.testing") : t("databaseHosts.test") }}
                      </button>
                      <button :class="buttonCls" @click="startEdit(row)">{{ t("databaseHosts.edit") }}</button>
                      <button :class="dangerCls" @click="remove(row)">{{ t("databaseHosts.remove") }}</button>
                    </div>
                  </td>
                </tr>
                <tr v-if="results[row.id]" class="border-b border-ink-800 last:border-0">
                  <td colspan="7" class="px-4 pb-3 text-sm" :class="results[row.id].ok ? 'text-ink-300' : 'text-bad'">
                    {{ results[row.id].ok ? `${t("databaseHosts.works")} (${results[row.id].message})` : results[row.id].message }}
                  </td>
                </tr>
              </template>
              <tr v-if="!rows.length">
                <td colspan="7" class="px-4 py-12 text-center">
                  <p class="font-semibold">{{ t("databaseHosts.empty") }}</p>
                  <p class="mt-1 text-sm text-ink-400">{{ t("databaseHosts.emptyHint") }}</p>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </AppLayout>
</template>
