<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";

interface Task {
  id: string;
  sequence: number;
  action: string;
  payload: string;
  time_offset: number;
  continue_on_failure: boolean;
}

interface Schedule {
  id: string;
  name: string;
  minute: string;
  hour: string;
  day_of_month: string;
  month: string;
  day_of_week: string;
  only_when_online: boolean;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  last_result: string | null;
  last_detail: string | null;
  timezone: string;
  is_running: boolean;
  tasks: Task[];
}

const props = defineProps<{ serverId: string; permissions: string[] }>();

const rows = ref<Schedule[]>([]);
const loading = ref(true);
const error = ref("");
const notice = ref("");
const busy = ref(false);
const showForm = ref(false);
const editing = ref<string | null>(null);
const expanded = ref<string | null>(null);
const addingTo = ref<string | null>(null);
const form = ref(emptyForm());
const taskForm = ref(emptyTask());
let timer: number | undefined;
let alive = true;

const can = (right: string) => props.permissions.includes(right);
const base = () => `/servers/${props.serverId}/schedules`;
const manage = computed(() => can("schedules.manage"));

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const primaryClass =
  "rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const ghostClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-accent-500 disabled:opacity-40";
const dangerClass =
  "rounded-md border border-bad/50 px-3 py-1.5 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-40";

function emptyForm() {
  return {
    name: "",
    minute: "0",
    hour: "4",
    day_of_month: "*",
    month: "*",
    day_of_week: "*",
    only_when_online: true,
    enabled: true,
  };
}

function emptyTask() {
  return { action: "power", payload: "restart", time_offset: 0, continue_on_failure: false };
}

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Could not reach the server.";
}

function when(iso: string | null): string {
  if (!iso) return "-";
  const fixed = /(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`;
  return new Date(fixed).toLocaleString();
}

const zoneName = computed(() => rows.value[0]?.timezone ?? "the panel time zone");

function taskLabel(t: Task): string {
  if (t.action === "power") return `Power: ${t.payload}`;
  if (t.action === "command") return `Command: ${t.payload}`;
  return t.payload ? `Backup (ignoring ${t.payload.replace(/\n/g, ", ")})` : "Create backup";
}

function resultText(s: Schedule): string {
  if (s.last_result === "ok") return "ok";
  return `${s.last_result ?? ""}${s.last_detail ? " - " + s.last_detail : ""}`;
}

function resultClass(s: Schedule): string {
  if (s.last_result === "ok") return "text-accent-400";
  if (s.last_result === "failed") return "text-bad";
  return "text-ink-400";
}

function plan() {
  window.clearTimeout(timer);
  if (alive && rows.value.some((r) => r.is_running)) {
    timer = window.setTimeout(load, 3000);
  }
}

async function load() {
  try {
    rows.value = await api<Schedule[]>(base());
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
    plan();
  }
}

function columns(s: Schedule): [string, string][] {
  return [
    ["Minute", s.minute],
    ["Hour", s.hour],
    ["Day (month)", s.day_of_month],
    ["Month", s.month],
    ["Day (week)", s.day_of_week],
  ];
}

function toggleOpen(s: Schedule) {
  expanded.value = expanded.value === s.id ? null : s.id;
  addingTo.value = null;
}

function openNew() {
  if (showForm.value && editing.value === null) {
    showForm.value = false;
    return;
  }
  editing.value = null;
  form.value = emptyForm();
  showForm.value = true;
}

function openEdit(s: Schedule) {
  editing.value = s.id;
  form.value = {
    name: s.name,
    minute: s.minute,
    hour: s.hour,
    day_of_month: s.day_of_month,
    month: s.month,
    day_of_week: s.day_of_week,
    only_when_online: s.only_when_online,
    enabled: s.enabled,
  };
  showForm.value = true;
}

function closeForm() {
  showForm.value = false;
  editing.value = null;
  form.value = emptyForm();
}

async function save() {
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    const body = { ...form.value, name: form.value.name.trim() };
    if (editing.value) {
      await api<Schedule>(`${base()}/${editing.value}`, { method: "PATCH", body });
      closeForm();
      notice.value = "Saved.";
      await load();
    } else {
      const created = await api<Schedule>(base(), { method: "POST", body });
      closeForm();
      expanded.value = created?.id ?? null;
      addingTo.value = created?.id ?? null;
      taskForm.value = emptyTask();
      notice.value = "Schedule created. Add at least one task so it can run.";
      await load();
    }
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function toggle(s: Schedule) {
  error.value = "";
  try {
    await api(`${base()}/${s.id}`, { method: "PATCH", body: { enabled: !s.enabled } });
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

async function remove(s: Schedule) {
  if (!window.confirm(`Delete the schedule "${s.name}"?`)) return;
  error.value = "";
  try {
    await api(`${base()}/${s.id}`, { method: "DELETE" });
    expanded.value = null;
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

function report(s: Schedule) {
  notice.value = "";
  if (s.last_result === "ok") {
    notice.value = `"${s.name}" finished successfully.`;
  } else {
    error.value = `"${s.name}" ${s.last_result ?? "failed"}: ${s.last_detail ?? "unknown error"}`;
  }
}

async function runNow(s: Schedule) {
  error.value = "";
  notice.value = "";
  const before = s.last_run_at;
  try {
    await api(`${base()}/${s.id}/execute`, { method: "POST" });
  } catch (e) {
    error.value = message(e);
    return;
  }
  notice.value = `"${s.name}" started.`;
  for (let i = 0; i < 40 && alive; i += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    await load();
    const current = rows.value.find((r) => r.id === s.id);
    if (current && current.last_run_at !== before && !current.is_running) {
      report(current);
      return;
    }
  }
  if (alive) notice.value = `"${s.name}" is still running.`;
}

function openTaskForm(s: Schedule) {
  addingTo.value = addingTo.value === s.id ? null : s.id;
  taskForm.value = emptyTask();
}

function onActionChange() {
  taskForm.value.payload = taskForm.value.action === "power" ? "restart" : "";
}

async function addTask(s: Schedule) {
  error.value = "";
  busy.value = true;
  try {
    await api(`${base()}/${s.id}/tasks`, {
      method: "POST",
      body: {
        action: taskForm.value.action,
        payload: taskForm.value.payload,
        time_offset: Number(taskForm.value.time_offset) || 0,
        continue_on_failure: taskForm.value.continue_on_failure,
      },
    });
    taskForm.value = emptyTask();
    await load();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function removeTask(s: Schedule, t: Task) {
  error.value = "";
  try {
    await api(`${base()}/${s.id}/tasks/${t.id}`, { method: "DELETE" });
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

onMounted(load);
onBeforeUnmount(() => {
  alive = false;
  window.clearTimeout(timer);
});
</script>

<template>
  <section class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-2xl font-semibold">Automations</h2>
        <p class="mt-2 text-sm text-ink-400">
          Automate server tasks with scheduled commands, power actions and backups. Times are in {{ zoneName }}.
        </p>
      </div>
      <button v-if="manage" :class="primaryClass" @click="openNew">New Schedule</button>
    </div>

    <p v-if="error" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="notice" role="status" class="rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-300">
      {{ notice }}
    </p>

    <form v-if="showForm" class="grid gap-4 rounded-xl border border-ink-700 bg-ink-900 p-5" @submit.prevent="save">
      <h3 class="text-lg font-semibold">{{ editing ? "Edit schedule" : "New schedule" }}</h3>
      <div>
        <label for="s-name" class="mb-1.5 block text-sm text-ink-300">Name</label>
        <input id="s-name" v-model="form.name" required maxlength="64" :class="inputClass" />
      </div>
      <div class="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <div>
          <label for="s-min" class="mb-1.5 block text-xs text-ink-400">Minute</label>
          <input id="s-min" v-model="form.minute" maxlength="32" :class="inputClass" />
        </div>
        <div>
          <label for="s-hour" class="mb-1.5 block text-xs text-ink-400">Hour</label>
          <input id="s-hour" v-model="form.hour" maxlength="32" :class="inputClass" />
        </div>
        <div>
          <label for="s-dom" class="mb-1.5 block text-xs text-ink-400">Day of month</label>
          <input id="s-dom" v-model="form.day_of_month" maxlength="32" :class="inputClass" />
        </div>
        <div>
          <label for="s-mon" class="mb-1.5 block text-xs text-ink-400">Month</label>
          <input id="s-mon" v-model="form.month" maxlength="32" :class="inputClass" />
        </div>
        <div>
          <label for="s-dow" class="mb-1.5 block text-xs text-ink-400">Day of week</label>
          <input id="s-dow" v-model="form.day_of_week" maxlength="32" :class="inputClass" />
        </div>
      </div>
      <p class="text-xs text-ink-400">
        Time in {{ zoneName }}. Use * for "every". Day of week: 0 is Sunday, 1 is Monday.
      </p>
      <label class="flex items-center gap-2 text-sm text-ink-300">
        <input v-model="form.only_when_online" type="checkbox" /> Only when the server is online
      </label>
      <label class="flex items-center gap-2 text-sm text-ink-300">
        <input v-model="form.enabled" type="checkbox" /> Schedule enabled
      </label>
      <div class="flex gap-2">
        <button type="submit" :class="primaryClass" :disabled="busy || !form.name.trim()">
          {{ editing ? "Save" : "Create" }}
        </button>
        <button type="button" :class="ghostClass" @click="closeForm">Cancel</button>
      </div>
    </form>

    <p v-if="loading" class="text-sm text-ink-400">Loading...</p>
    <div
      v-else-if="rows.length === 0"
      class="flex min-h-[16rem] items-center justify-center rounded-xl border border-ink-700 bg-ink-900 text-center"
    >
      <div>
        <h3 class="text-lg font-semibold">No schedules found</h3>
        <p class="mt-2 text-sm text-ink-400">This server does not have any schedules yet.</p>
      </div>
    </div>

    <ul v-else class="space-y-3">
      <li v-for="s in rows" :key="s.id" class="rounded-xl border border-ink-700 bg-ink-900">
        <button type="button" class="flex w-full items-center gap-4 px-5 py-4 text-left" @click="toggleOpen(s)">
          <svg class="h-5 w-5 shrink-0 text-ink-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 5h18v16H3z M3 10h18 M8 3v4 M16 3v4" />
          </svg>
          <div class="min-w-0 flex-1">
            <p class="truncate text-lg font-medium">{{ s.name }}</p>
            <p class="text-xs text-ink-400">Last run at: {{ s.last_run_at ? when(s.last_run_at) : "never" }}</p>
            <p v-if="s.last_result" class="truncate text-xs" :class="resultClass(s)">
              Last result: {{ resultText(s) }}
            </p>
          </div>
          <div class="hidden gap-5 md:flex">
            <div v-for="[label, value] in columns(s)" :key="label" class="text-center">
              <p class="text-base font-medium">{{ value }}</p>
              <p class="text-[10px] uppercase tracking-wide text-ink-400">{{ label }}</p>
            </div>
          </div>
          <span
            class="shrink-0 rounded-full bg-ink-700 px-3 py-1 text-xs font-medium uppercase"
            :class="s.is_running || s.enabled ? 'text-accent-400' : 'text-ink-400'"
          >
            {{ s.is_running ? "Running" : s.enabled ? "Active" : "Inactive" }}
          </span>
        </button>

        <div v-if="expanded === s.id" class="space-y-4 border-t border-ink-700 px-5 py-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <p class="text-xs text-ink-400">
              Next run: {{ s.enabled ? when(s.next_run_at) : "-" }}
              <span v-if="s.only_when_online"> · only when online</span>
            </p>
            <div v-if="manage" class="flex flex-wrap gap-2">
              <button :class="ghostClass" :disabled="s.is_running || s.tasks.length === 0" @click="runNow(s)">
                Run now
              </button>
              <button :class="ghostClass" @click="openTaskForm(s)">Add task</button>
              <button :class="ghostClass" :disabled="s.is_running" @click="openEdit(s)">Edit</button>
              <button :class="ghostClass" @click="toggle(s)">{{ s.enabled ? "Disable" : "Enable" }}</button>
              <button :class="dangerClass" :disabled="s.is_running" @click="remove(s)">Delete</button>
            </div>
          </div>

          <ol v-if="s.tasks.length" class="space-y-2">
            <li v-for="(t, i) in s.tasks" :key="t.id" class="flex items-start justify-between gap-3 text-sm">
              <span class="min-w-0 break-words text-ink-300">
                {{ i + 1 }}. {{ taskLabel(t) }}
                <span v-if="t.time_offset > 0" class="text-xs text-ink-400"> · after {{ t.time_offset }}s</span>
                <span v-if="t.continue_on_failure" class="text-xs text-ink-400"> · continues on failure</span>
              </span>
              <button v-if="manage" :class="dangerClass" @click="removeTask(s, t)">Remove</button>
            </li>
          </ol>
          <p v-else class="text-xs text-ink-400">No tasks yet. A schedule without tasks does nothing.</p>

          <form v-if="addingTo === s.id && manage" class="grid gap-3 border-t border-ink-700 pt-4" @submit.prevent="addTask(s)">
            <div>
              <label :for="`t-action-${s.id}`" class="mb-1.5 block text-sm text-ink-300">Action</label>
              <select :id="`t-action-${s.id}`" v-model="taskForm.action" :class="inputClass" @change="onActionChange">
                <option value="power">Power action</option>
                <option value="command">Send command</option>
                <option value="backup">Create backup</option>
              </select>
            </div>
            <div v-if="taskForm.action === 'power'">
              <label :for="`t-power-${s.id}`" class="mb-1.5 block text-sm text-ink-300">Power action</label>
              <select :id="`t-power-${s.id}`" v-model="taskForm.payload" :class="inputClass">
                <option value="start">Start</option>
                <option value="stop">Stop</option>
                <option value="restart">Restart</option>
                <option value="kill">Kill</option>
              </select>
            </div>
            <div v-else-if="taskForm.action === 'command'">
              <label :for="`t-cmd-${s.id}`" class="mb-1.5 block text-sm text-ink-300">Command</label>
              <input :id="`t-cmd-${s.id}`" v-model="taskForm.payload" maxlength="1024" :class="inputClass" />
            </div>
            <div v-else>
              <label :for="`t-ign-${s.id}`" class="mb-1.5 block text-sm text-ink-300">
                Ignored files (optional, one pattern per line)
              </label>
              <textarea :id="`t-ign-${s.id}`" v-model="taskForm.payload" rows="3" maxlength="1024" :class="inputClass" />
            </div>
            <div>
              <label :for="`t-off-${s.id}`" class="mb-1.5 block text-sm text-ink-300">
                Wait before this task (seconds)
              </label>
              <input :id="`t-off-${s.id}`" v-model.number="taskForm.time_offset" type="number" min="0" :class="inputClass" />
            </div>
            <label class="flex items-center gap-2 text-sm text-ink-300">
              <input v-model="taskForm.continue_on_failure" type="checkbox" /> Continue if this task fails
            </label>
            <div class="flex gap-2">
              <button type="submit" :class="primaryClass" :disabled="busy">Add task</button>
              <button type="button" :class="ghostClass" @click="addingTo = null">Close</button>
            </div>
          </form>
        </div>
      </li>
    </ul>
  </section>
</template>
