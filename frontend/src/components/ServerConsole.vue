<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";

const props = defineProps<{
  serverId: string;
  serverName: string;
}>();

const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();

const output = ref("");
const command = ref("");
const status = ref("connecting");
const error = ref("");
const terminal = ref<HTMLElement | null>(null);
let socket: WebSocket | null = null;

function append(value: string): void {
  output.value += value;
  void nextTick(() => {
    if (terminal.value) {
      terminal.value.scrollTop = terminal.value.scrollHeight;
    }
  });
}

function socketUrl(ticket: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/servers/${props.serverId}/console?ticket=${encodeURIComponent(ticket)}`;
}

async function connect(): Promise<void> {
  try {
    const { ticket } = await api<{ ticket: string }>(`/servers/${props.serverId}/console/ticket`, {
      method: "POST",
      body: {},
    });
    socket = new WebSocket(socketUrl(ticket));
    socket.onopen = () => {
      status.value = "connected";
      error.value = "";
    };
    socket.onmessage = (event) => {
      try {
        const frame = JSON.parse(event.data) as {
          type?: string;
          data?: string;
          status?: string;
          message?: string;
        };
        if (frame.type === "output" && frame.data) {
          append(frame.data);
        } else if (frame.type === "status" && frame.status) {
          status.value = frame.status;
        } else if (frame.type === "error") {
          error.value = frame.message ?? t("console.connectionError");
        }
      } catch {
        append(event.data);
      }
    };
    socket.onerror = () => {
      status.value = "error";
      error.value = t("console.connectionError");
    };
    socket.onclose = () => {
      if (status.value !== "error") {
        status.value = "closed";
      }
    };
  } catch (cause) {
    status.value = "error";
    error.value = cause instanceof ApiError ? cause.message : t("console.connectionError");
  }
}

function send(): void {
  const value = command.value.trim();
  if (!value || socket?.readyState !== WebSocket.OPEN) {
    return;
  }
  socket.send(JSON.stringify({ type: "input", data: value }));
  command.value = "";
}

function close(): void {
  socket?.close();
  emit("close");
}

onMounted(() => void connect());
onBeforeUnmount(() => socket?.close());
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

      <div ref="terminal" class="min-h-[22rem] flex-1 overflow-auto bg-[#090a0c] p-4 font-mono text-xs leading-5 text-ink-200">
        <pre class="whitespace-pre-wrap break-words">{{ output || t("console.waiting") }}</pre>
      </div>

      <p v-if="error" class="border-t border-bad/30 bg-bad/10 px-4 py-2 text-xs text-bad">{{ error }}</p>

      <form class="flex gap-2 border-t border-ink-700 p-3" @submit.prevent="send">
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
