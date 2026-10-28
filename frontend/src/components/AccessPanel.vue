<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import { auth } from "../stores/auth";

interface Member {
  id: string;
  user_id: string;
  email: string;
  permissions: string[];
  created_at: string;
}

interface AccessData {
  owner_id: string | null;
  members: Member[];
  available_permissions: string[];
  can_manage: boolean;
}

type Dialog = { kind: "add" } | { kind: "edit"; member: Member } | { kind: "remove"; member: Member };

const props = defineProps<{ serverId: string; permissions: string[] }>();
const { t, te } = useI18n();

const ORDER = ["console", "power", "files", "startup", "settings", "backups", "databases", "allocations", "schedules", "access"];

const data = ref<AccessData | null>(null);
const loading = ref(true);
const error = ref("");
const dialog = ref<Dialog | null>(null);
const busy = ref(false);
const formError = ref("");
const email = ref("");
const selected = ref<string[]>([]);

const canView = computed(() => props.permissions.includes("access.view"));
const meId = computed(() => auth.state.user?.id);
const base = computed(() => `/servers/${props.serverId}/access`);

function groupsFor(perms: string[]): { key: string; items: string[] }[] {
  const by = new Map<string, string[]>();
  for (const p of perms) {
    const key = p.split(".")[0];
    by.set(key, [...(by.get(key) ?? []), p]);
  }
  const rank = (key: string): number => {
    const i = ORDER.indexOf(key);
    return i === -1 ? ORDER.length : i;
  };
  return [...by.entries()]
    .sort((a, b) => rank(a[0]) - rank(b[0]))
    .map(([key, items]) => ({ key, items: [...items].sort() }));
}

const dialogGroups = computed(() => {
  const current = dialog.value;
  const available = data.value?.available_permissions ?? [];
  const extra = current && current.kind === "edit" ? current.member.permissions : [];
  return groupsFor([...new Set([...available, ...extra])]);
});

function permLabel(p: string): string {
  const key = `access.perm.${p}`;
  return te(key) ? t(key) : p;
}

function groupLabel(key: string): string {
  const k = `access.group.${key}`;
  return te(k) ? t(k) : key;
}

function isAvailable(p: string): boolean {
  return data.value?.available_permissions.includes(p) ?? false;
}

function isSelf(member: Member): boolean {
  return member.user_id === meId.value;
}

function editable(member: Member): boolean {
  return !!data.value?.can_manage && !isSelf(member) && member.permissions.every(isAvailable);
}

function removable(member: Member): boolean {
  return !!data.value?.can_manage && (isSelf(member) || editable(member));
}

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : t("access.actionFailed");
}

async function load(): Promise<void> {
  try {
    data.value = await api<AccessData>(base.value);
    error.value = "";
  } catch (cause) {
    error.value = cause instanceof ApiError ? cause.message : t("access.loadFailed");
  } finally {
    loading.value = false;
  }
}

function openDialog(next: Dialog): void {
  formError.value = "";
  email.value = "";
  selected.value = next.kind === "edit" ? [...next.member.permissions] : [];
  dialog.value = next;
}

function closeDialog(): void {
  dialog.value = null;
}

function setGroup(items: string[], on: boolean): void {
  const rest = selected.value.filter((p) => !items.includes(p));
  selected.value = on ? [...rest, ...items.filter(isAvailable)] : rest;
}

async function submit(): Promise<void> {
  const current = dialog.value;
  if (!current || busy.value) return;
  busy.value = true;
  formError.value = "";
  try {
    if (current.kind === "add") {
      await api(base.value, { method: "POST", body: { email: email.value, permissions: selected.value } });
    } else if (current.kind === "edit") {
      await api(`${base.value}/${current.member.id}`, { method: "PUT", body: { permissions: selected.value } });
    } else {
      await api(`${base.value}/${current.member.id}`, { method: "DELETE" });
    }
    closeDialog();
    await load();
  } catch (cause) {
    formError.value = message(cause);
  } finally {
    busy.value = false;
  }
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape" && dialog.value && !busy.value) closeDialog();
}

onMounted(() => {
  window.addEventListener("keydown", onKey);
  if (canView.value) void load();
  else loading.value = false;
});

onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const linkButton = "rounded px-2 py-1 text-xs text-ink-300 transition hover:bg-ink-800 hover:text-ink-100";
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-2xl font-semibold">{{ t("access.title") }}</h2>
        <p class="mt-2 text-sm text-ink-400">{{ t("access.subtitle") }}</p>
      </div>
      <button
        v-if="data?.can_manage"
        class="shrink-0 rounded-md bg-accent-500 px-3 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400"
        @click="openDialog({ kind: 'add' })"
      >
        {{ t("access.addUser") }}
      </button>
    </div>

    <p v-if="!canView" class="rounded-lg border border-ink-700 bg-ink-900 px-4 py-3 text-sm text-ink-300">
      {{ t("access.noAccess") }}
    </p>

    <template v-else>
      <p v-if="error" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
        {{ error }}
      </p>

      <div v-if="data && data.members.length > 0" class="divide-y divide-ink-800 rounded-xl border border-ink-700 bg-ink-900">
        <div v-for="member in data.members" :key="member.id" class="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-medium">
              {{ member.email }}
              <span v-if="isSelf(member)" class="ml-1.5 text-xs font-normal text-ink-400">({{ t("access.you") }})</span>
            </p>
            <div class="mt-1.5 flex flex-wrap gap-1.5">
              <span v-if="member.permissions.length === 0" class="rounded bg-ink-800 px-1.5 py-0.5 text-xs text-ink-300">
                {{ t("access.noPermissions") }}
              </span>
              <span
                v-for="group in groupsFor(member.permissions)"
                :key="group.key"
                class="rounded bg-ink-800 px-1.5 py-0.5 text-xs text-ink-300"
              >
                {{ groupLabel(group.key) }} · {{ group.items.length }}
              </span>
            </div>
          </div>
          <div class="flex shrink-0 gap-1">
            <button v-if="editable(member)" :class="linkButton" @click="openDialog({ kind: 'edit', member })">
              {{ t("access.edit") }}
            </button>
            <button
              v-if="removable(member)"
              class="rounded px-2 py-1 text-xs text-bad transition hover:bg-bad/10"
              @click="openDialog({ kind: 'remove', member })"
            >
              {{ t("access.remove") }}
            </button>
          </div>
        </div>
      </div>

      <div
        v-else-if="!loading && !error"
        class="rounded-xl border border-dashed border-ink-700 px-6 py-12 text-center"
      >
        <p class="font-medium">{{ t("access.emptyTitle") }}</p>
        <p class="mt-1 text-sm text-ink-400">{{ t("access.emptyBody") }}</p>
      </div>

      <p class="text-xs text-ink-400">{{ t("access.note") }}</p>
    </template>

    <div
      v-if="dialog"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
      @mousedown.self="!busy && closeDialog()"
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="access-dialog-title"
        class="max-h-[90vh] w-full max-w-lg space-y-4 overflow-y-auto rounded-lg border border-ink-700 bg-ink-900 p-6"
        @submit.prevent="submit"
      >
        <h3 id="access-dialog-title" class="text-lg font-semibold tracking-tight">
          {{
            dialog.kind === "add"
              ? t("access.addTitle")
              : dialog.kind === "edit"
                ? t("access.editTitle")
                : t("access.removeTitle")
          }}
        </h3>

        <template v-if="dialog.kind !== 'remove'">
          <div v-if="dialog.kind === 'add'">
            <label for="access-email" class="mb-1.5 block text-sm text-ink-300">{{ t("access.email") }}</label>
            <input id="access-email" v-model="email" type="email" required autofocus autocomplete="off" :class="inputClass" />
            <p class="mt-1.5 text-xs text-ink-400">{{ t("access.emailHint") }}</p>
          </div>
          <p v-else class="text-sm text-ink-300">{{ dialog.member.email }}</p>

          <fieldset class="space-y-4">
            <legend class="mb-1 text-sm text-ink-300">{{ t("access.permissionsLabel") }}</legend>
            <div v-for="group in dialogGroups" :key="group.key" class="rounded-md border border-ink-700 p-3">
              <div class="mb-2 flex items-center justify-between">
                <span class="text-sm font-medium">{{ groupLabel(group.key) }}</span>
                <span class="flex gap-1">
                  <button type="button" :class="linkButton" @click="setGroup(group.items, true)">{{ t("access.all") }}</button>
                  <button type="button" :class="linkButton" @click="setGroup(group.items, false)">{{ t("access.none") }}</button>
                </span>
              </div>
              <label
                v-for="permission in group.items"
                :key="permission"
                class="flex items-center gap-2.5 py-1 text-sm"
                :class="isAvailable(permission) ? '' : 'opacity-50'"
              >
                <input
                  v-model="selected"
                  type="checkbox"
                  :value="permission"
                  :disabled="busy || !isAvailable(permission)"
                  class="h-4 w-4 accent-accent-500"
                />
                {{ permLabel(permission) }}
              </label>
            </div>
          </fieldset>
        </template>

        <p v-else class="text-sm text-ink-300">
          {{
            dialog.member.user_id === meId
              ? t("access.removeSelfBody")
              : t("access.removeBody", { email: dialog.member.email })
          }}
        </p>

        <p v-if="formError" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {{ formError }}
        </p>

        <div class="flex justify-end gap-2 pt-1">
          <button
            type="button"
            :disabled="busy"
            class="rounded-md border border-ink-700 px-3 py-2 text-sm text-ink-300 transition hover:border-ink-600 hover:text-ink-100"
            @click="closeDialog"
          >
            {{ t("access.cancel") }}
          </button>
          <button
            type="submit"
            :disabled="busy"
            class="rounded-md px-3 py-2 text-sm font-semibold transition disabled:opacity-60"
            :class="dialog.kind === 'remove' ? 'bg-bad text-white hover:opacity-90' : 'bg-accent-500 text-ink-950 hover:bg-accent-400'"
          >
            {{ dialog.kind === "add" ? t("access.add") : dialog.kind === "edit" ? t("access.save") : t("access.remove") }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
