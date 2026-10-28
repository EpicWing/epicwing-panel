<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { api, ApiError } from "../api/client";
import AppLayout from "../components/AppLayout.vue";
import { auth } from "../stores/auth";

interface UserRow {
  id: string;
  email: string;
  is_admin: boolean;
  disabled_at: string | null;
  created_at: string;
  two_factor_enabled: boolean;
  server_count: number;
}

type Dialog =
  | { kind: "create" }
  | { kind: "edit"; user: UserRow }
  | { kind: "password"; user: UserRow }
  | { kind: "delete"; user: UserRow };

const { t } = useI18n();

const users = ref<UserRow[]>([]);
const query = ref("");
const loaded = ref(false);
const loadError = ref("");
const actionError = ref("");
const dialog = ref<Dialog | null>(null);
const busy = ref(false);
const formError = ref("");
const form = reactive({ email: "", password: "", isAdmin: false });

const meId = computed(() => auth.state.user?.id);
const target = computed<UserRow | null>(() =>
  dialog.value && "user" in dialog.value ? dialog.value.user : null,
);

let searchTimer: number | undefined;
let sequence = 0;

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : t("users.actionFailed");
}

async function load(): Promise<void> {
  const current = ++sequence;
  const params = new URLSearchParams({ limit: "500" });
  if (query.value.trim()) params.set("q", query.value.trim());
  try {
    const result = await api<UserRow[]>(`/users?${params.toString()}`);
    if (current !== sequence) return;
    users.value = result;
    loadError.value = "";
  } catch (cause) {
    if (current !== sequence) return;
    loadError.value = cause instanceof ApiError ? cause.message : t("users.loadFailed");
  } finally {
    if (current === sequence) loaded.value = true;
  }
}

watch(query, () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(load, 250);
});

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape" && dialog.value && !busy.value) closeDialog();
}

onMounted(() => {
  void load();
  window.addEventListener("keydown", onKey);
});

onBeforeUnmount(() => {
  window.clearTimeout(searchTimer);
  window.removeEventListener("keydown", onKey);
});

function openDialog(next: Dialog): void {
  formError.value = "";
  form.email = next.kind === "edit" ? next.user.email : "";
  form.password = "";
  form.isAdmin = next.kind === "edit" ? next.user.is_admin : false;
  dialog.value = next;
}

function closeDialog(): void {
  dialog.value = null;
  form.password = "";
}

async function submit(): Promise<void> {
  const current = dialog.value;
  if (!current || busy.value) return;
  busy.value = true;
  formError.value = "";
  try {
    if (current.kind === "create") {
      await api("/users", {
        method: "POST",
        body: { email: form.email, password: form.password, is_admin: form.isAdmin },
      });
    } else if (current.kind === "edit") {
      await api(`/users/${current.user.id}`, {
        method: "PATCH",
        body: { email: form.email, is_admin: form.isAdmin },
      });
    } else if (current.kind === "password") {
      await api(`/users/${current.user.id}/password`, {
        method: "POST",
        body: { new_password: form.password },
      });
    } else {
      await api(`/users/${current.user.id}`, { method: "DELETE" });
    }
    closeDialog();
    await load();
  } catch (cause) {
    formError.value = message(cause);
  } finally {
    busy.value = false;
  }
}

async function toggleDisabled(user: UserRow): Promise<void> {
  actionError.value = "";
  try {
    await api(`/users/${user.id}/${user.disabled_at ? "enable" : "disable"}`, { method: "POST" });
    await load();
  } catch (cause) {
    actionError.value = message(cause);
  }
}

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString();
}

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const linkButton =
  "rounded px-2 py-1 text-xs text-ink-300 transition hover:bg-ink-800 hover:text-ink-100";
</script>

<template>
  <AppLayout area="admin" wide :title="t('users.title')" :subtitle="t('users.subtitle')">
    <template #actions>
      <button
        class="rounded-md bg-accent-500 px-3 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400"
        @click="openDialog({ kind: 'create' })"
      >
        {{ t("users.newUser") }}
      </button>
    </template>

    <div class="mb-4">
      <label for="user-search" class="sr-only">{{ t("users.search") }}</label>
      <input
        id="user-search"
        v-model="query"
        type="search"
        :placeholder="t('users.search')"
        class="w-full max-w-sm rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm outline-none transition focus:border-accent-500"
      />
    </div>

    <p
      v-if="loadError || actionError"
      role="alert"
      class="mb-4 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
    >
      {{ loadError || actionError }}
    </p>

    <div v-if="users.length > 0" class="overflow-x-auto rounded-lg border border-ink-700 bg-ink-900">
      <table class="w-full min-w-[56rem] text-left text-sm">
        <thead class="border-b border-ink-700 text-xs uppercase tracking-wide text-ink-400">
          <tr>
            <th class="px-4 py-3 font-medium">{{ t("users.email") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("users.role") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("users.status") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("users.twoFactor") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("users.servers") }}</th>
            <th class="px-4 py-3 font-medium">{{ t("users.created") }}</th>
            <th class="px-4 py-3 text-right font-medium">
              <span class="sr-only">{{ t("users.manage") }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id" class="border-b border-ink-800 last:border-0">
            <td class="px-4 py-3">
              {{ user.email }}
              <span v-if="user.id === meId" class="ml-1.5 text-xs text-ink-400">({{ t("users.you") }})</span>
            </td>
            <td class="px-4 py-3">
              <span
                class="rounded px-1.5 py-0.5 text-xs font-medium"
                :class="user.is_admin ? 'bg-accent-500/15 text-accent-400' : 'bg-ink-800 text-ink-300'"
              >
                {{ user.is_admin ? t("users.roleAdmin") : t("users.roleUser") }}
              </span>
            </td>
            <td class="px-4 py-3">
              <span
                class="rounded px-1.5 py-0.5 text-xs font-medium"
                :class="user.disabled_at ? 'bg-bad/15 text-bad' : 'bg-ok/15 text-ok'"
              >
                {{ user.disabled_at ? t("users.statusDisabled") : t("users.statusActive") }}
              </span>
            </td>
            <td class="px-4 py-3 text-ink-300">{{ user.two_factor_enabled ? t("users.on") : t("users.off") }}</td>
            <td class="px-4 py-3 text-ink-300">{{ user.server_count }}</td>
            <td class="px-4 py-3 text-ink-300">{{ formatDate(user.created_at) }}</td>
            <td class="whitespace-nowrap px-4 py-3 text-right">
              <button :class="linkButton" @click="openDialog({ kind: 'edit', user })">{{ t("users.edit") }}</button>
              <button
                v-if="user.id !== meId"
                :class="linkButton"
                @click="toggleDisabled(user)"
              >
                {{ user.disabled_at ? t("users.enable") : t("users.disable") }}
              </button>
              <button
                v-if="user.id !== meId"
                :class="linkButton"
                @click="openDialog({ kind: 'password', user })"
              >
                {{ t("users.resetPassword") }}
              </button>
              <button
                v-if="user.id !== meId"
                class="rounded px-2 py-1 text-xs text-bad transition hover:bg-bad/10"
                @click="openDialog({ kind: 'delete', user })"
              >
                {{ t("users.delete") }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-else-if="loaded && !loadError"
      class="rounded-lg border border-dashed border-ink-700 px-6 py-14 text-center"
    >
      <p class="font-medium">{{ t("users.emptyTitle") }}</p>
      <p class="mt-1 text-sm text-ink-400">{{ t("users.emptyBody") }}</p>
    </div>

    <div
      v-if="dialog"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
      @mousedown.self="!busy && closeDialog()"
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="users-dialog-title"
        class="w-full max-w-md space-y-4 rounded-lg border border-ink-700 bg-ink-900 p-6"
        @submit.prevent="submit"
      >
        <h2 id="users-dialog-title" class="text-lg font-semibold tracking-tight">
          {{
            dialog.kind === "create"
              ? t("users.createTitle")
              : dialog.kind === "edit"
                ? t("users.editTitle")
                : dialog.kind === "password"
                  ? t("users.resetTitle")
                  : t("users.deleteTitle")
          }}
        </h2>

        <template v-if="dialog.kind === 'create' || dialog.kind === 'edit'">
          <div>
            <label for="user-email" class="mb-1.5 block text-sm text-ink-300">{{ t("users.email") }}</label>
            <input
              id="user-email"
              v-model="form.email"
              type="email"
              autocomplete="off"
              required
              autofocus
              :class="inputClass"
            />
          </div>
          <div v-if="dialog.kind === 'create'">
            <label for="user-password" class="mb-1.5 block text-sm text-ink-300">{{ t("users.password") }}</label>
            <input
              id="user-password"
              v-model="form.password"
              type="password"
              autocomplete="new-password"
              minlength="12"
              required
              :class="inputClass"
            />
            <p class="mt-1.5 text-xs text-ink-400">{{ t("users.passwordHint") }}</p>
          </div>
          <label
            v-if="dialog.kind === 'create' || target?.id !== meId"
            class="flex items-start gap-2.5 text-sm"
          >
            <input v-model="form.isAdmin" type="checkbox" class="mt-0.5 h-4 w-4 accent-accent-500" />
            <span>
              {{ t("users.administrator") }}
              <span class="block text-xs text-ink-400">{{ t("users.administratorHint") }}</span>
            </span>
          </label>
        </template>

        <template v-else-if="dialog.kind === 'password'">
          <p class="text-sm text-ink-300">{{ t("users.resetBody") }}</p>
          <div>
            <label for="user-new-password" class="mb-1.5 block text-sm text-ink-300">{{ t("users.newPassword") }}</label>
            <input
              id="user-new-password"
              v-model="form.password"
              type="password"
              autocomplete="new-password"
              minlength="12"
              required
              autofocus
              :class="inputClass"
            />
            <p class="mt-1.5 text-xs text-ink-400">{{ t("users.passwordHint") }}</p>
          </div>
        </template>

        <p v-else class="text-sm text-ink-300">{{ t("users.deleteBody", { email: target?.email ?? "" }) }}</p>

        <p
          v-if="formError"
          role="alert"
          class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
        >
          {{ formError }}
        </p>

        <div class="flex justify-end gap-2 pt-1">
          <button
            type="button"
            :disabled="busy"
            class="rounded-md border border-ink-700 px-3 py-2 text-sm text-ink-300 transition hover:border-ink-600 hover:text-ink-100"
            @click="closeDialog"
          >
            {{ t("users.cancel") }}
          </button>
          <button
            type="submit"
            :disabled="busy"
            class="rounded-md px-3 py-2 text-sm font-semibold transition disabled:opacity-60"
            :class="dialog.kind === 'delete' ? 'bg-bad text-white hover:opacity-90' : 'bg-accent-500 text-ink-950 hover:bg-accent-400'"
          >
            {{
              dialog.kind === "create"
                ? t("users.create")
                : dialog.kind === "edit"
                  ? t("users.save")
                  : dialog.kind === "password"
                    ? t("users.reset")
                    : t("users.delete")
            }}
          </button>
        </div>
      </form>
    </div>
  </AppLayout>
</template>
