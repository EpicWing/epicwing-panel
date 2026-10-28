<script setup lang="ts">
import { ref, watch } from "vue";

import { ApiError, api } from "../api/client";

type Mode = "off" | "crash" | "always";
interface Saved {
  auto_restart: Mode;
  auto_restart_delay: number;
  auto_restart_max_failures: number;
}

const props = defineProps<{
  serverId: string;
  mode: Mode;
  delay: number;
  maxFailures: number;
  dueAt: string | null;
}>();
const emit = defineEmits<{ (e: "saved", value: Saved): void }>();

const modeValue = ref<Mode>(props.mode);
const delayValue = ref<number | "">(props.delay);
const failuresValue = ref<number | "">(props.maxFailures);
const busy = ref(false);
const error = ref("");
const done = ref(false);

const fieldCls =
  "mt-1 w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500 disabled:opacity-50";

watch(
  () => [props.mode, props.delay, props.maxFailures] as const,
  ([mode, delay, failures]) => {
    modeValue.value = mode;
    delayValue.value = delay;
    failuresValue.value = failures;
  },
);

function whole(value: number | "", min: number, max: number): value is number {
  return value !== "" && Number.isInteger(value) && value >= min && value <= max;
}

async function save() {
  error.value = "";
  done.value = false;
  const delay = delayValue.value;
  const failures = failuresValue.value;
  if (!whole(delay, 5, 3600)) {
    error.value = "The delay must be a whole number of seconds between 5 and 3600.";
    return;
  }
  if (!whole(failures, 0, 100)) {
    error.value = "Failed attempts must be a whole number between 0 and 100.";
    return;
  }
  busy.value = true;
  const body: Saved = {
    auto_restart: modeValue.value,
    auto_restart_delay: delay,
    auto_restart_max_failures: failures,
  };
  try {
    await api(`/servers/${props.serverId}`, { method: "PATCH", body });
    emit("saved", body);
    done.value = true;
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "Could not reach the server.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="rounded-xl border border-ink-700 bg-ink-900 p-6">
    <h3 class="text-lg font-semibold">Automatic Restart</h3>
    <p class="mt-2 text-sm text-ink-400">
      Starts the server again when it stops by itself. Stopping it from the panel or typing a stop command in the
      console never triggers a restart.
    </p>
    <p v-if="dueAt" role="status" class="mt-4 rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm">
      Automatic restart scheduled for {{ new Date(dueAt).toLocaleTimeString() }}.
    </p>
    <p v-if="error" role="alert" class="mt-4 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <form class="mt-5 space-y-4" @submit.prevent="save">
      <div>
        <label for="ar-mode" class="block text-sm text-ink-400">Restart</label>
        <select id="ar-mode" v-model="modeValue" :class="fieldCls">
          <option value="off">Never</option>
          <option value="crash">Only after a crash</option>
          <option value="always">Always, also after a clean exit</option>
        </select>
      </div>
      <div class="grid gap-4 sm:grid-cols-2">
        <div>
          <label for="ar-delay" class="block text-sm text-ink-400">Delay (seconds)</label>
          <input
            id="ar-delay"
            v-model.number="delayValue"
            type="number"
            min="5"
            max="3600"
            :disabled="modeValue === 'off'"
            :class="fieldCls"
          />
          <p class="mt-1 text-xs text-ink-400">Wait time before the restart, 5 to 3600.</p>
        </div>
        <div>
          <label for="ar-failures" class="block text-sm text-ink-400">Failed attempts before giving up</label>
          <input
            id="ar-failures"
            v-model.number="failuresValue"
            type="number"
            min="0"
            max="100"
            :disabled="modeValue === 'off'"
            :class="fieldCls"
          />
          <p class="mt-1 text-xs text-ink-400">
            Stops within 5 minutes after an automatic start count as failed. 0 never gives up.
          </p>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <button
          type="submit"
          :disabled="busy"
          class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60"
        >
          Save
        </button>
        <span v-if="done" class="text-sm text-ink-300">Saved.</span>
      </div>
    </form>
  </div>
</template>
