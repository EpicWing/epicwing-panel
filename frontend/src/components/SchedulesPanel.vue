<script setup lang="ts">
import cronstrue from "cronstrue";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";
import Modal from "./Modal.vue";

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
const formError = ref("");
const busy = ref(false);
const scheduleOpen = ref(false);
const taskOpen = ref(false);
const editing = ref<string | null>(null);
const taskFor = ref<string | null>(null);
const expanded = ref<string | null>(null);
const form = ref(emptyForm());
const taskForm = ref(emptyTask());
let timer: number | undefined;
let alive = true;

const can = (right: string) => props.permissions.includes(right);
const base = () => `/servers/${props.serverId}/schedules`;
const manage = computed(() => can("schedules.manage"));

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-800 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const primaryClass =
  "rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const cancelClass =
  "rounded-md bg-ink-800 px-4 py-2 text-sm text-ink-300 transition hover:text-ink-100";
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
  return new Date(fixed).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

const zoneName = computed(() => rows.value[0]?.timezone ?? "the panel time zone");

function sentence(parts: string[]): string {
  try {
    return cronstrue.toString(parts.map((p) => p.trim()).join(" "), { use24HourTimeFormat: true });
  } catch {
    return "";
  }
}

function describeSchedule(s: Schedule): string {
  return sentence([s.minute, s.hour, s.day_of_month, s.month, s.day_of_week]);
}

const liveDescription = computed(() => {
  const f = form.value;
  const text = sentence([f.minute, f.hour, f.day_of_month, f.month, f.day_of_week]);
  return text
    ? { ok: true, text }
    : { ok: false, text: 'These values do not make a valid timing yet. Use * for "every".' };
});

const powerText: Record<string, string> = {
  start: "Start the server",
  stop: "Stop the server",
  restart: "Restart the server",
  kill: "Kill the server",
};

function taskLabel(t: Task): string {
  if (t.action === "power") return powerText[t.payload] ?? `Power: ${t.payload}`;
  if (t.action === "command") return `Run command: ${t.payload}`;
  return t.payload
    ? `Create a backup, leaving out ${t.payload.replace(/\n/g, ", ")}`
    : "Create a backup";
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

function toggleOpen(s: Schedule) {
  expanded.value = expanded.value === s.id ? null : s.id;
}

function openNew() {
  editing.value = null;
  form.value = emptyForm();
  formError.value = "";
  scheduleOpen.value = true;
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
  formError.value = "";
  scheduleOpen.value = true;
}

function closeForm() {
  scheduleOpen.value = false;
  editing.value = null;
}

async function save() {
  formError.value = "";
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    const body = { ...form.value, name: form.value.name.trim() };
    if (editing.value) {
      await api<Schedule>(`${base()}/${editing.value}`, { method: "PATCH", body });
      closeForm();
      notice.value = "Changes saved.";
      await load();
    } else {
      const created = await api<Schedule>(base(), { method: "POST", body });
      closeForm();
      expanded.value = created?.id ?? null;
      notice.value = "Automation created. Add a step so it has something to do.";
      await load();
    }
  } catch (e) {
    formError.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function remove(s: Schedule) {
  if (!window.confirm(`Delete the automation "${s.name}"?`)) return;
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
  taskFor.value = s.id;
  taskForm.value = emptyTask();
  formError.value = "";
  taskOpen.value = true;
}

function onActionChange() {
  taskForm.value.payload = taskForm.value.action === "power" ? "restart" : "";
}

async function addTask() {
  if (!taskFor.value) return;
  formError.value = "";
  busy.value = true;
  try {
    await api(`${base()}/${taskFor.value}/tasks`, {
      method: "POST",
      body: {
        action: taskForm.value.action,
        payload: taskForm.value.payload,
        time_offset: Number(taskForm.value.time_offset) || 0,
        continue_on_failure: taskForm.value.continue_on_failure,
      },
    });
    taskOpen.value = false;
    notice.value = "Step added.";
    await load();
  } catch (e) {
    formError.value = message(e);
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
          Run power actions, console commands and backups on a timer. Times follow {{ zoneName }}.
        </p>
      </div>
      <button v-if="manage" type="button" :class="primaryClass" @click="openNew">+ New automation</button>
    </div>

    <p v-if="error" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <p v-if="notice" role="status" class="rounded-md border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-300">
      {{ notice }}
    </p>

    <div v-if="loading" class="space-y-3" aria-busy="true"><div class="skeleton h-12"></div><div class="skeleton h-12"></div><div class="skeleton h-12"></div></div>
    <div
      v-else-if="rows.length === 0"
      class="flex min-h-[16rem] items-center justify-center rounded-xl border border-ink-700 bg-ink-900 px-6 text-center"
    >
      <div>
        <h3 class="text-lg font-semibold">No automations yet</h3>
        <p class="mt-2 text-sm text-ink-400">
          Create one to restart, back up or send commands to this server on a timer.
        </p>
      </div>
    </div>

    <ul v-else class="space-y-3">
      <li v-for="s in rows" :key="s.id" class="rounded-xl border border-ink-700 bg-ink-900">
        <button type="button" class="flex w-full items-center gap-4 px-5 py-4 text-left" @click="toggleOpen(s)">
          <svg class="h-5 w-5 shrink-0 text-ink-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
          <div class="min-w-0 flex-1">
            <p class="truncate text-lg font-medium">{{ s.name }}</p>
            <p class="text-sm text-ink-300">{{ describeSchedule(s) || "Custom timing" }}</p>
            <p class="mt-1 text-xs text-ink-400">
              Next: {{ s.enabled ? when(s.next_run_at) : "-" }}
              · Last: {{ s.last_run_at ? when(s.last_run_at) : "never" }}
            </p>
            <p v-if="s.last_result" class="truncate text-xs" :class="resultClass(s)">
              Result: {{ resultText(s) }}
            </p>
          </div>
          <span
            class="shrink-0 rounded-full bg-ink-700 px-3 py-1 text-xs font-medium uppercase"
            :class="s.is_running || s.enabled ? 'text-accent-400' : 'text-ink-400'"
          >
            {{ s.is_running ? "Running" : s.enabled ? "On" : "Paused" }}
          </span>
        </button>

        <div v-if="expanded === s.id" class="space-y-4 border-t border-ink-700 px-5 py-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <p class="text-xs text-ink-400">
              {{ s.tasks.length }} {{ s.tasks.length === 1 ? "step" : "steps" }}
              <span v-if="s.only_when_online"> · skipped while the server is offline</span>
            </p>
            <div v-if="manage" class="flex flex-wrap gap-2">
              <button :class="ghostClass" :disabled="s.is_running || s.tasks.length === 0" @click="runNow(s)">Run now</button>
              <button :class="ghostClass" @click="openTaskForm(s)">Add step</button>
              <button :class="ghostClass" :disabled="s.is_running" @click="openEdit(s)">Edit</button>
              <button :class="dangerClass" :disabled="s.is_running" @click="remove(s)">Delete</button>
            </div>
          </div>

          <ol v-if="s.tasks.length" class="space-y-2">
            <li v-for="(t, i) in s.tasks" :key="t.id" class="flex items-start justify-between gap-3 text-sm">
              <span class="min-w-0 break-words text-ink-300">
                {{ i + 1 }}. {{ taskLabel(t) }}
                <span v-if="t.time_offset > 0" class="text-xs text-ink-400"> · waits {{ t.time_offset }}s first</span>
                <span v-if="t.continue_on_failure" class="text-xs text-ink-400"> · goes on if it fails</span>
              </span>
              <button v-if="manage" :class="dangerClass" @click="removeTask(s, t)">Remove</button>
            </li>
          </ol>
          <p v-else class="text-xs text-ink-400">No steps yet. An automation without steps does nothing.</p>
        </div>
      </li>
    </ul>

    <Modal v-model="scheduleOpen" :title="editing ? 'Edit automation' : 'New automation'">
      <form id="schedule-form" class="grid gap-4" @submit.prevent="save">
        <p v-if="formError" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{{ formError }}</p>
        <div>
          <label for="s-name" class="mb-1.5 block text-sm text-ink-300">Name</label>
          <input id="s-name" v-model="form.name" required maxlength="64" placeholder="Nightly restart" :class="inputClass" />
        </div>
        <div>
          <p class="mb-1.5 text-sm text-ink-300">When should it run?</p>
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <div>
              <label for="s-min" class="mb-1.5 block text-xs text-ink-400">Minute</label>
              <input id="s-min" v-model="form.minute" maxlength="32" :class="[inputClass, 'font-mono']" />
            </div>
            <div>
              <label for="s-hour" class="mb-1.5 block text-xs text-ink-400">Hour</label>
              <input id="s-hour" v-model="form.hour" maxlength="32" :class="[inputClass, 'font-mono']" />
            </div>
            <div>
              <label for="s-dom" class="mb-1.5 block text-xs text-ink-400">Day of month</label>
              <input id="s-dom" v-model="form.day_of_month" maxlength="32" :class="[inputClass, 'font-mono']" />
            </div>
            <div>
              <label for="s-mon" class="mb-1.5 block text-xs text-ink-400">Month</label>
              <input id="s-mon" v-model="form.month" maxlength="32" :class="[inputClass, 'font-mono']" />
            </div>
            <div>
              <label for="s-dow" class="mb-1.5 block text-xs text-ink-400">Day of week</label>
              <input id="s-dow" v-model="form.day_of_week" maxlength="32" :class="[inputClass, 'font-mono']" />
            </div>
          </div>
          <div
            class="mt-3 rounded-md border border-ink-700 bg-ink-800 px-3 py-2 text-sm"
            :class="liveDescription.ok ? 'text-ink-100' : 'text-ink-400'"
          >
            {{ liveDescription.text }}
          </div>
          <p class="mt-1.5 text-xs text-ink-400">
            Use * for "every". Day of week starts at 0 for Sunday. Times follow {{ zoneName }}.
          </p>
        </div>
        <label class="flex cursor-pointer items-center justify-between gap-4 rounded-md border border-ink-700 bg-ink-800 px-4 py-3">
          <span>
            <span class="block text-sm font-medium">Skip while offline</span>
            <span class="block text-xs text-ink-400">Do not run this automation when the server is stopped.</span>
          </span>
          <input v-model="form.only_when_online" type="checkbox" class="h-4 w-4 shrink-0 accent-accent-500" />
        </label>
        <label class="flex cursor-pointer items-center justify-between gap-4 rounded-md border border-ink-700 bg-ink-800 px-4 py-3">
          <span>
            <span class="block text-sm font-medium">Turned on</span>
            <span class="block text-xs text-ink-400">Switch it off to pause the automation without deleting it.</span>
          </span>
          <input v-model="form.enabled" type="checkbox" class="h-4 w-4 shrink-0 accent-accent-500" />
        </label>
      </form>
      <template #footer>
        <button type="button" :class="cancelClass" @click="closeForm">Cancel</button>
        <button type="submit" form="schedule-form" :class="primaryClass" :disabled="busy || !form.name.trim()">
          <span v-if="busy" class="spinner mr-2"></span>{{ editing ? "Save changes" : "Create" }}
        </button>
      </template>
    </Modal>

    <Modal v-model="taskOpen" title="Add step">
      <form id="task-form" class="grid gap-4" @submit.prevent="addTask">
        <p v-if="formError" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{{ formError }}</p>
        <div>
          <label for="t-action" class="mb-1.5 block text-sm text-ink-300">What should happen?</label>
          <select id="t-action" v-model="taskForm.action" :class="inputClass" @change="onActionChange">
            <option value="power">Power action</option>
            <option value="command">Console command</option>
            <option value="backup">Backup</option>
          </select>
        </div>
        <div v-if="taskForm.action === 'power'">
          <label for="t-power" class="mb-1.5 block text-sm text-ink-300">Which action?</label>
          <select id="t-power" v-model="taskForm.payload" :class="inputClass">
            <option value="start">Start</option>
            <option value="stop">Stop</option>
            <option value="restart">Restart</option>
            <option value="kill">Kill</option>
          </select>
        </div>
        <div v-else-if="taskForm.action === 'command'">
          <label for="t-cmd" class="mb-1.5 block text-sm text-ink-300">Command</label>
          <input id="t-cmd" v-model="taskForm.payload" required maxlength="1024" placeholder="say Restarting soon" :class="[inputClass, 'font-mono']" />
        </div>
        <div v-else>
          <label for="t-ign" class="mb-1.5 block text-sm text-ink-300">Leave out (optional)</label>
          <textarea id="t-ign" v-model="taskForm.payload" rows="3" maxlength="1024" :class="[inputClass, 'font-mono text-xs']"></textarea>
          <p class="mt-1.5 text-xs text-ink-400">One file or folder pattern per line. Matching files are not part of the backup.</p>
        </div>
        <div>
          <label for="t-off" class="mb-1.5 block text-sm text-ink-300">Wait first (seconds)</label>
          <input id="t-off" v-model.number="taskForm.time_offset" type="number" min="0" :class="inputClass" />
          <p class="mt-1.5 text-xs text-ink-400">A pause before this step starts. It has no effect on the first step.</p>
        </div>
        <label class="flex cursor-pointer items-center justify-between gap-4 rounded-md border border-ink-700 bg-ink-800 px-4 py-3">
          <span>
            <span class="block text-sm font-medium">Keep going if this fails</span>
            <span class="block text-xs text-ink-400">The next steps still run when this one fails.</span>
          </span>
          <input v-model="taskForm.continue_on_failure" type="checkbox" class="h-4 w-4 shrink-0 accent-accent-500" />
        </label>
      </form>
      <template #footer>
        <button type="button" :class="cancelClass" @click="taskOpen = false">Cancel</button>
        <button type="submit" form="task-form" :class="primaryClass" :disabled="busy">
          <span v-if="busy" class="spinner mr-2"></span>Add step
        </button>
      </template>
    </Modal>
  </section>
</template>
