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

const PRESETS: { label: string; f: [string, string, string, string, string] }[] = [
  { label: "Every day at 04:00", f: ["0", "4", "*", "*", "*"] },
  { label: "Every hour", f: ["0", "*", "*", "*", "*"] },
  { label: "Every 30 minutes", f: ["*/30", "*", "*", "*", "*"] },
  { label: "Every Monday at 03:00", f: ["0", "3", "*", "*", "1"] },
];

function emptyForm() {
  return {
    name: "",
    minute: "0",
    hour: "4",
    day_of_month: "*",
    month: "*",
    day_of_week: "*",
    only_when_online: true,
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

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function isNum(s: string): boolean {
  return /^\d+$/.test(s);
}

function two(s: string): string {
  return s.padStart(2, "0");
}

function describe(f: {
  minute: string;
  hour: string;
  day_of_month: string;
  month: string;
  day_of_week: string;
}): string {
  const m = f.minute.trim();
  const h = f.hour.trim();
  const dom = f.day_of_month.trim();
  const mon = f.month.trim();
  const dow = f.day_of_week.trim();
  let text: string;
  if (m === "*" && h === "*") {
    text = "Every minute";
  } else if (m.startsWith("*/") && h === "*") {
    text = `Every ${m.slice(2)} minutes`;
  } else if (isNum(m) && h === "*") {
    text = `At minute ${m} of every hour`;
  } else if (isNum(m) && h.startsWith("*/")) {
    text = `At minute ${m}, every ${h.slice(2)} hours`;
  } else if (isNum(m) && isNum(h)) {
    const now = new Date();
    const local = new Date(
      Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), Number(h), Number(m)),
    ).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    text = `At ${two(h)}:${two(m)} UTC (${local} your time)`;
  } else {
    text = `Minute ${m}, hour ${h} (UTC)`;
  }
  const parts = [text];
  if (dow !== "*") {
    parts.push(isNum(dow) && Number(dow) <= 7 ? `on ${DAYS[Number(dow) % 7]}` : `on weekdays ${dow}`);
  }
  if (dom !== "*") parts.push(`on day ${dom} of the month`);
  if (mon !== "*") parts.push(`in month ${mon}`);
  return parts.join(", ");
}

function taskLabel(t: Task): string {
  if (t.action === "power") return `Power: ${t.payload}`;
  if (t.action === "command") return `Command: ${t.payload}`;
  return t.payload ? `Backup (ignoring ${t.payload.replace(/\n/g, ", ")})` : "Create backup";
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

function usePreset(f: [string, string, string, string, string]) {
  form.value.minute = f[0];
  form.value.hour = f[1];
  form.value.day_of_month = f[2];
  form.value.month = f[3];
  form.value.day_of_week = f[4];
}

async function create() {
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    const created = await api<Schedule>(base(), {
      method: "POST",
      body: { ...form.value, name: form.value.name.trim(), enabled: true },
    });
    showForm.value = false;
    form.value = emptyForm();
    addingTo.value = created?.id ?? null;
    taskForm.value = emptyTask();
    notice.value = "Schedule created. Add at least one task so it can run.";
    await load();
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
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

async function runNow(s: Schedule) {
  error.value = "";
  notice.value = "";
  try {
    await api(`${base()}/${s.id}/execute`, { method: "POST" });
    notice.value = `"${s.name}" started.`;
    await load();
    window.setTimeout(load, 1500);
  } catch (e) {
    error.value = message(e);
  }
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
          Automate server tasks with scheduled commands, power actions and backups. Times are in UTC.
        </p>
      </div>
      <button v-if="manage" :class="primaryClass" @click="showForm = !showForm">New Schedule</button>
    </div>

    <p v-if="error" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="notice" role="status" class="rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-300">
      {{ notice }}
    </p>

    <form v-if="showForm" class="grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5" @submit.prevent="create">
      <div>
        <label for="s-name" class="mb-1.5 block text-sm text-ink-300">Name</label>
        <input id="s-name" v-model="form.name" required maxlength="64" :class="inputClass" />
      </div>
      <div class="flex flex-wrap gap-2">
        <button v-for="p in PRESETS" :key="p.label" type="button" :class="ghostClass" @click="usePreset(p.f)">
          {{ p.label }}
        </button>
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
      <p class="text-sm text-ink-300">{{ describe(form) }}</p>
      <p class="text-xs text-ink-400">
        Only digits and the characters * / , - are allowed. Day of week: 0 or 7 is Sunday, 1 is Monday.
      </p>
      <label class="flex items-center gap-2 text-sm text-ink-300">
        <input v-model="form.only_when_online" type="checkbox" /> Only run when the server is online
      </label>
      <div class="flex gap-2">
        <button type="submit" :class="primaryClass" :disabled="busy || !form.name.trim()">Create</button>
        <button type="button" :class="ghostClass" @click="showForm = false">Cancel</button>
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
      <li v-for="s in rows" :key="s.id" class="rounded-xl border border-ink-700 bg-ink-900 p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate font-medium">
              {{ s.name }}
              <span v-if="s.is_running" class="ml-2 text-xs text-accent-400">running</span>
              <span v-else-if="!s.enabled" class="ml-2 text-xs text-ink-400">paused</span>
            </p>
            <p class="mt-1 text-xs text-ink-300">{{ describe(s) }}</p>
            <p class="mt-1 text-xs text-ink-400">
              Next: {{ s.enabled ? when(s.next_run_at) : "-" }} · Last: {{ when(s.last_run_at) }}
              <span v-if="s.only_when_online"> · only when online</span>
            </p>
          </div>
          <div v-if="manage" class="flex flex-wrap gap-2">
            <button :class="ghostClass" :disabled="s.is_running || s.tasks.length === 0" @click="runNow(s)">
              Run now
            </button>
            <button :class="ghostClass" @click="openTaskForm(s)">Add task</button>
            <button :class="ghostClass" @click="toggle(s)">{{ s.enabled ? "Pause" : "Enable" }}</button>
            <button :class="dangerClass" :disabled="s.is_running" @click="remove(s)">Delete</button>
          </div>
        </div>

        <ol v-if="s.tasks.length" class="mt-4 space-y-2 border-t border-ink-700 pt-4">
          <li v-for="(t, i) in s.tasks" :key="t.id" class="flex items-start justify-between gap-3 text-sm">
            <span class="min-w-0 break-words text-ink-300">
              {{ i + 1 }}. {{ taskLabel(t) }}
              <span v-if="t.time_offset > 0" class="text-xs text-ink-400"> · after {{ t.time_offset }}s</span>
              <span v-if="t.continue_on_failure" class="text-xs text-ink-400"> · continues on failure</span>
            </span>
            <button v-if="manage" :class="dangerClass" @click="removeTask(s, t)">Remove</button>
          </li>
        </ol>
        <p v-else class="mt-4 border-t border-ink-700 pt-4 text-xs text-ink-400">
          No tasks yet. A schedule without tasks does nothing.
        </p>

        <form
          v-if="addingTo === s.id && manage"
          class="mt-4 grid gap-3 border-t border-ink-700 pt-4"
          @submit.prevent="addTask(s)"
        >
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
      </li>
    </ul>
  </section>
</template>
