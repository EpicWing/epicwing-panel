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

interface Candidate {
  id: string;
  email: string;
}

type Dialog = { kind: "add" } | { kind: "edit"; member: Member } | { kind: "remove"; member: Member };

const props = defineProps<{ serverId: string; permissions: string[] }>();
const { t, te } = useI18n();

const ORDER = ["console", "power", "files", "startup", "settings", "backups", "databases", "allocations", "schedules", "access"];

// Simple line icons (24x24), so no extra library is needed.
const ICONS: Record<string, string> = {
  console: "M4 17l6-6-6-6 M12 19h8",
  power: "M18.36 6.64a9 9 0 1 1-12.73 0 M12 2v10",
  files: "M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9l-.8-1.2A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z",
  startup: "M5 3l14 9-14 9V3z",
  settings: "M4 21v-7 M4 10V3 M12 21v-9 M12 8V3 M20 21v-5 M20 12V3 M1 14h6 M9 8h6 M17 16h6",
  backups: "M21 8v13H3V8 M1 3h22v5H1z M10 12h4",
  databases: "M3 6c0-1.7 4-3 9-3s9 1.3 9 3-4 3-9 3-9-1.3-9-3z M21 12c0 1.7-4 3-9 3s-9-1.3-9-3 M3 6v12c0 1.7 4 3 9 3s9-1.3 9-3V6",
  allocations: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z M2 12h20 M12 2a15 15 0 0 1 0 20 M12 2a15 15 0 0 0 0 20",
  schedules: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z M12 6v6l4 2",
  access: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
};

// Starting points for the form. Only permissions that the user may give are applied.
const PRESETS = [
  {
    key: "viewer",
    label: "Viewer",
    hint: "Watch the console and see backups",
    permissions: ["console.view", "backups.view"],
  },
  {
    key: "operator",
    label: "Operator",
    hint: "Viewer, and send commands, start, stop and restart",
    permissions: [
      "console.view",
      "backups.view",
      "console.command",
      "power.start",
      "power.stop",
      "power.restart",
    ],
  },
  {
    key: "manager",
    label: "Manager",
    hint: "Operator, and files, backups, schedules, and view startup and settings",
    permissions: [
      "console.view",
      "backups.view",
      "console.command",
      "power.start",
      "power.stop",
      "power.restart",
      "files.read",
      "files.write",
      "backups.create",
      "backups.download",
      "backups.restore",
      "schedules.view",
      "schedules.manage",
      "startup.view",
      "settings.view",
    ],
  },
];

const data = ref<AccessData | null>(null);
const loading = ref(true);
const error = ref("");
const dialog = ref<Dialog | null>(null);
const busy = ref(false);
const formError = ref("");
const selected = ref<string[]>([]);
const candidates = ref<Candidate[]>([]);
const candidatesLoading = ref(false);
const search = ref("");
const chosen = ref("");
let searchTimer: ReturnType<typeof setTimeout> | undefined;

const canView = computed(() => props.permissions.includes("access.view"));
const meId = computed(() => auth.state.user?.id);
const base = computed(() => `/servers/${props.serverId}/access`);

function iconPath(key: string): string {
  return ICONS[key] ?? "M12 12h.01";
}

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

function permDesc(p: string): string {
  const key = `access.permDesc.${p}`;
  return te(key) ? t(key) : "";
}

function groupLabel(key: string): string {
  const k = `access.group.${key}`;
  return te(k) ? t(k) : key;
}

function groupDesc(key: string): string {
  const k = `access.groupDesc.${key}`;
  return te(k) ? t(k) : "";
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

async function loadCandidates(): Promise<void> {
  candidatesLoading.value = true;
  try {
    const q = encodeURIComponent(search.value.trim());
    candidates.value = await api<Candidate[]>(`${base.value}/candidates?q=${q}`);
    if (!candidates.value.some((c) => c.id === chosen.value)) {
      chosen.value = candidates.value[0]?.id ?? "";
    }
  } catch (cause) {
    formError.value = message(cause);
  } finally {
    candidatesLoading.value = false;
  }
}

function onSearch(): void {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => void loadCandidates(), 250);
}

function openDialog(next: Dialog): void {
  formError.value = "";
  search.value = "";
  chosen.value = "";
  candidates.value = [];
  selected.value = next.kind === "edit" ? [...next.member.permissions] : [];
  dialog.value = next;
  if (next.kind === "add") void loadCandidates();
}

function closeDialog(): void {
  clearTimeout(searchTimer);
  dialog.value = null;
}

function applyPreset(perms: string[]): void {
  selected.value = perms.filter(isAvailable);
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
      const pick = candidates.value.find((c) => c.id === chosen.value);
      if (!pick) {
        formError.value = t("access.selectUserFirst");
        return;
      }
      await api(base.value, { method: "POST", body: { email: pick.email, permissions: selected.value } });
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

onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  clearTimeout(searchTimer);
});

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const linkButton = "rounded px-2 py-1 text-xs text-ink-300 transition hover:bg-ink-800 hover:text-ink-100";
</script>

<template>
  <div class="space-y-6">
    <form v-if="dialog && dialog.kind !== 'remove'" class="space-y-6" @submit.prevent="submit">
      <div>
        <button type="button" :disabled="busy" :class="linkButton" @click="closeDialog">
          &larr; {{ t("access.back") }}
        </button>
        <h2 class="mt-2 text-2xl font-semibold">
          {{ dialog.kind === "add" ? t("access.addTitle") : t("access.editTitle") }}
        </h2>
        <p v-if="dialog.kind === 'add'" class="mt-2 text-sm text-ink-400">{{ t("access.addSubtitle") }}</p>
        <p v-else class="mt-2 text-sm text-ink-300">{{ dialog.member.email }}</p>
      </div>

      <div v-if="dialog.kind === 'add'" class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="mb-3 text-sm font-medium">{{ t("access.selectUser") }}</p>
        <div class="grid gap-3 sm:grid-cols-2">
          <input
            v-model="search"
            type="search"
            autocomplete="off"
            :placeholder="t('access.searchUsers')"
            :class="inputClass"
            @input="onSearch"
          />
          <select
            id="access-user"
            v-model="chosen"
            :disabled="busy || candidates.length === 0"
            :class="inputClass"
            :aria-label="t('access.selectUser')"
          >
            <option v-for="candidate in candidates" :key="candidate.id" :value="candidate.id">
              {{ candidate.email }}
            </option>
          </select>
        </div>
        <p class="mt-2 text-xs text-ink-400">
          {{
            candidatesLoading
              ? t("access.loadingUsers")
              : candidates.length > 0
                ? t("access.selectUserHint")
                : search.trim().length < 3
                  ? t("access.searchHint")
                  : t("access.noMatch")
          }}
        </p>
      </div>

      <div class="rounded-xl border border-ink-700 bg-ink-900 p-5">
        <p class="text-sm font-medium">Presets</p>
        <p class="mt-1 text-xs text-ink-400">Pick a starting point, then change single permissions below.</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <button
            v-for="preset in PRESETS"
            :key="preset.key"
            type="button"
            :disabled="busy"
            class="rounded-md border border-ink-700 px-3 py-1.5 text-left transition hover:border-ink-600 hover:bg-ink-800"
            @click="applyPreset(preset.permissions)"
          >
            <span class="block text-sm font-medium">{{ preset.label }}</span>
            <span class="block text-xs text-ink-400">{{ preset.hint }}</span>
          </button>
          <button
            type="button"
            :disabled="busy"
            class="rounded-md border border-ink-700 px-3 py-1.5 text-sm text-ink-300 transition hover:border-ink-600 hover:bg-ink-800"
            @click="applyPreset([])"
          >
            Clear all
          </button>
        </div>
      </div>

      <fieldset class="space-y-4">
        <legend class="mb-1 text-sm font-medium text-ink-200">{{ t("access.permissionsLabel") }}</legend>
        <div v-for="group in dialogGroups" :key="group.key" class="rounded-xl border border-ink-700 bg-ink-900 p-5">
          <div class="mb-4 flex items-start justify-between gap-3">
            <div class="flex items-start gap-3">
              <span class="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent-500/15 text-accent-400">
                <svg
                  viewBox="0 0 24 24"
                  class="h-5 w-5"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  aria-hidden="true"
                >
                  <path :d="iconPath(group.key)" />
                </svg>
              </span>
              <div>
                <p class="text-sm font-semibold">{{ groupLabel(group.key) }}</p>
                <p v-if="groupDesc(group.key)" class="text-xs text-ink-400">{{ groupDesc(group.key) }}</p>
              </div>
            </div>
            <span class="flex shrink-0 gap-1">
              <button type="button" :class="linkButton" @click="setGroup(group.items, true)">{{ t("access.all") }}</button>
              <button type="button" :class="linkButton" @click="setGroup(group.items, false)">{{ t("access.none") }}</button>
            </span>
          </div>
          <div class="grid gap-x-10 gap-y-4 sm:grid-cols-2">
            <label
              v-for="permission in group.items"
              :key="permission"
              class="flex items-start gap-3 text-sm"
              :class="isAvailable(permission) ? 'cursor-pointer' : 'opacity-50'"
            >
              <input
                v-model="selected"
                type="checkbox"
                :value="permission"
                :disabled="busy || !isAvailable(permission)"
                class="mt-0.5 h-4 w-4 shrink-0 accent-accent-500"
              />
              <span>
                <span class="block font-medium">{{ permLabel(permission) }}</span>
                <span v-if="permDesc(permission)" class="block text-xs text-ink-400">{{ permDesc(permission) }}</span>
              </span>
            </label>
          </div>
        </div>
      </fieldset>

      <p v-if="formError" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
        {{ formError }}
      </p>

      <div class="flex justify-end gap-2">
        <button
          type="button"
          :disabled="busy"
          class="rounded-md border border-ink-700 px-4 py-2 text-sm text-ink-300 transition hover:border-ink-600 hover:text-ink-100"
          @click="closeDialog"
        >
          {{ t("access.cancel") }}
        </button>
        <button
          type="submit"
          :disabled="busy || (dialog.kind === 'add' && !chosen)"
          class="rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60"
        >
          {{ dialog.kind === "add" ? t("access.add") : t("access.save") }}
        </button>
      </div>
    </form>

    <template v-else>
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
    </template>

    <div
      v-if="dialog && dialog.kind === 'remove'"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
      @mousedown.self="!busy && closeDialog()"
    >
      <form
        role="dialog"
        aria-modal="true"
        class="w-full max-w-md space-y-4 rounded-xl border border-ink-700 bg-ink-900 p-6"
        @submit.prevent="submit"
      >
        <h3 class="text-lg font-semibold tracking-tight">{{ t("access.removeTitle") }}</h3>
        <p class="text-sm text-ink-300">
          {{
            dialog.member.user_id === meId
              ? t("access.removeSelfBody")
              : t("access.removeBody", { email: dialog.member.email })
          }}
        </p>
        <p v-if="formError" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
          {{ formError }}
        </p>
        <div class="flex justify-end gap-2">
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
            class="rounded-md bg-bad px-3 py-2 text-sm font-semibold text-white transition hover:opacity-90 disabled:opacity-60"
          >
            {{ t("access.remove") }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
