<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { useServerConsole } from "../composables/useServerConsole";
import ConsoleOutput from "./ConsoleOutput.vue";

const props = defineProps<{
  serverId: string;
  serverName: string;
}>();

const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();

const command = ref("");
const { lines, status, error, connect, send, close: closeSocket } = useServerConsole();

function submit(): void {
  if (send(command.value)) command.value = "";
}

function close(): void {
  closeSocket();
  emit("close");
}

onMounted(() => void connect(props.serverId));
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" @click.self="close">
    <section class="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-900 shadow-2xl">
      <header class="flex items-center justify-between border-b border-ink-700 px-5 py-4">
        <div class="min-w-0">
          <h2 class="truncate font-semibold">{{ props.serverName }}</h2>
          <p class="mt-1 text-xs text-ink-400">
            {{ t("console.title") }} · {{ status }}
          </p>
        </div>
        <button class="rounded-md border border-ink-700 px-3 py-1.5 text-sm text-ink-300 hover:text-ink-100" @click="close">
          {{ t("console.close") }}
        </button>
      </header>

      <ConsoleOutput :lines="lines" :placeholder="t('console.waiting')" class="min-h-[22rem] flex-1" />

      <p v-if="error" class="border-t border-bad/30 bg-bad/10 px-4 py-2 text-xs text-bad">{{ error }}</p>

      <form class="flex gap-2 border-t border-ink-700 p-3" @submit.prevent="submit">
        <input
          v-model="command"
          class="min-w-0 flex-1 rounded-md border border-ink-700 bg-ink-950 px-3 py-2 font-mono text-sm outline-none focus:border-accent-500"
          :placeholder="t('console.placeholder')"
          :disabled="status !== 'connected' && status !== 'running'"
          autocomplete="off"
        />
        <button class="rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 hover:bg-accent-400 disabled:opacity-50" :disabled="!command.trim() || (status !== 'connected' && status !== 'running')">
          {{ t("console.send") }}
        </button>
      </form>
    </section>
  </div>
</template>
