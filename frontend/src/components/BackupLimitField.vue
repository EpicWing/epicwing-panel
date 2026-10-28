<script setup lang="ts">
import { ref, watch } from "vue";

import { ApiError, api } from "../api/client";

const props = defineProps<{ serverId: string; limit: number }>();
const emit = defineEmits<{ (e: "saved", value: number): void }>();

const value = ref<number | "">(props.limit);
const busy = ref(false);
const error = ref("");
const done = ref(false);

watch(
  () => props.limit,
  (next) => {
    value.value = next;
  },
);

async function save() {
  error.value = "";
  done.value = false;
  if (value.value === "" || !Number.isInteger(value.value) || value.value < 0 || value.value > 1000) {
    error.value = "Enter a whole number between 0 and 1000.";
    return;
  }
  busy.value = true;
  try {
    await api(`/servers/${props.serverId}`, { method: "PATCH", body: { backup_limit: value.value } });
    emit("saved", value.value);
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
    <h3 class="text-lg font-semibold">Backup Limit</h3>
    <p class="mt-2 text-sm text-ink-400">Maximum number of backups for this server. 0 disables backups.</p>
    <p v-if="error" role="alert" class="mt-4 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">
      {{ error }}
    </p>
    <form class="mt-5 flex items-center gap-3" @submit.prevent="save">
      <input
        v-model.number="value"
        type="number"
        min="0"
        max="1000"
        class="w-32 rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500"
      />
      <button
        type="submit"
        :disabled="busy"
        class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60"
      >
        Save
      </button>
      <span v-if="done" class="text-sm text-ink-300">Saved.</span>
    </form>
  </div>
</template>
