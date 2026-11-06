<script setup lang="ts">
import { ref, watch } from "vue";

import { ApiError, api } from "../api/client";

const props = defineProps<{
  serverId: string;
  memoryMb: number;
  cpus: number;
  diskMb: number;
  running: boolean;
}>();

const emit = defineEmits<{
  saved: [value: { memory_mb: number; cpus: number; disk_mb: number }];
}>();

const memory = ref(String(props.memoryMb));
const cpus = ref(String(props.cpus));
const disk = ref(String(props.diskMb));
// Solange nichts getippt wurde, folgen die Felder den Werten vom Server
const touched = ref(false);
const busy = ref(false);
const saved = ref(false);
const error = ref("");

watch(
  () => [props.memoryMb, props.cpus, props.diskMb],
  () => {
    if (touched.value) return;
    memory.value = String(props.memoryMb);
    cpus.value = String(props.cpus);
    disk.value = String(props.diskMb);
  },
);

const inputClass =
  "w-full rounded-lg border border-ink-700 bg-ink-950 px-4 py-3 text-sm text-ink-100 outline-none transition focus:border-accent-500";

function edit() {
  touched.value = true;
  saved.value = false;
}

// Leere Eingabe zählt als ungültig, 0 heißt unbegrenzt
function number(text: string): number | null {
  const value = Number(text.trim().replace(",", "."));
  return text.trim() !== "" && Number.isFinite(value) && value >= 0 ? value : null;
}

async function save() {
  error.value = "";
  saved.value = false;
  const memory_mb = number(memory.value);
  const cpuValue = number(cpus.value);
  const disk_mb = number(disk.value);
  if (memory_mb === null || cpuValue === null || disk_mb === null) {
    error.value = "Please enter numbers of 0 or more.";
    return;
  }
  busy.value = true;
  try {
    await api(`/servers/${props.serverId}`, {
      method: "PATCH",
      body: { memory_mb: Math.round(memory_mb), cpus: cpuValue, disk_mb: Math.round(disk_mb) },
    });
    emit("saved", { memory_mb: Math.round(memory_mb), cpus: cpuValue, disk_mb: Math.round(disk_mb) });
    touched.value = false;
    saved.value = true;
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : "The panel could not be reached.";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="rounded-xl border border-ink-700 bg-ink-900 p-6">
    <h3 class="text-lg font-semibold">Resources</h3>
    <p class="mt-2 text-sm text-ink-400">
      Memory, CPU and storage of this server. Use 0 for unlimited.
      <span v-if="running">The server is running, new values apply after the next restart.</span>
      <span v-else>New values apply at the next start.</span>
    </p>
    <form class="mt-5 grid gap-4 sm:grid-cols-3" @submit.prevent="save">
      <div>
        <label for="res-memory" class="mb-1.5 block text-sm text-ink-400">Memory (MB)</label>
        <input id="res-memory" v-model="memory" inputmode="numeric" :class="inputClass" @input="edit" />
      </div>
      <div>
        <label for="res-cpus" class="mb-1.5 block text-sm text-ink-400">CPU (cores)</label>
        <input id="res-cpus" v-model="cpus" inputmode="decimal" :class="inputClass" @input="edit" />
      </div>
      <div>
        <label for="res-disk" class="mb-1.5 block text-sm text-ink-400">Storage (MB)</label>
        <input id="res-disk" v-model="disk" inputmode="numeric" :class="inputClass" @input="edit" />
      </div>
      <div class="sm:col-span-3">
        <button
          type="submit"
          :disabled="busy || !touched"
          class="rounded-lg bg-accent-500 px-5 py-2 text-sm font-medium text-ink-950 transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {{ busy ? "Saving…" : "Save" }}
        </button>
        <p v-if="error" role="alert" class="mt-3 text-sm text-bad">{{ error }}</p>
        <p v-else-if="saved" class="mt-3 text-sm text-ink-400">Saved.</p>
      </div>
    </form>
  </div>
</template>
