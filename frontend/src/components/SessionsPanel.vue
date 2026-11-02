<script setup lang="ts">
import { onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";

interface SessionRow {
  id: string;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
  last_seen_at: string;
  current: boolean;
}

const rows = ref<SessionRow[]>([]);
const loaded = ref(false);
const error = ref("");
const busyId = ref("");

function device(ua: string | null): string {
  if (!ua) return "Unknown device";
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /OPR\/|Opera/.test(ua)
      ? "Opera"
      : /Firefox\//.test(ua)
        ? "Firefox"
        : /Chrome\//.test(ua)
          ? "Chrome"
          : /Safari\//.test(ua)
            ? "Safari"
            : "Browser";
  // Android and iPhone user agents also contain "Linux" or "Mac OS X", so they come first.
  const os = /Windows/.test(ua)
    ? "Windows"
    : /Android/.test(ua)
      ? "Android"
      : /iPhone|iPad/.test(ua)
        ? "iOS"
        : /Mac OS X/.test(ua)
          ? "macOS"
          : /Linux/.test(ua)
            ? "Linux"
            : "";
  return os ? `${browser} on ${os}` : browser;
}

function ago(value: string): string {
  const s = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 129600) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

function message(cause: unknown, fallback: string): string {
  return cause instanceof ApiError ? cause.message : fallback;
}

async function load(): Promise<void> {
  try {
    rows.value = await api<SessionRow[]>("/auth/sessions");
    error.value = "";
  } catch (cause) {
    error.value = message(cause, "Could not load the sessions.");
  } finally {
    loaded.value = true;
  }
}

async function end(row: SessionRow): Promise<void> {
  busyId.value = row.id;
  try {
    await api<void>(`/auth/sessions/${row.id}`, { method: "DELETE" });
    rows.value = rows.value.filter((r) => r.id !== row.id);
    error.value = "";
  } catch (cause) {
    error.value = message(cause, "Could not end the session.");
  } finally {
    busyId.value = "";
  }
}

onMounted(load);
</script>

<template>
  <section class="rounded-xl border border-ink-700 bg-ink-900 p-6">
    <h2 class="text-lg font-semibold">Active sessions</h2>
    <p class="mt-1 text-sm text-ink-400">Devices that are signed in to your account right now.</p>

    <p
      v-if="error"
      role="alert"
      class="mt-4 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
    >
      {{ error }}
    </p>

    <div v-if="!loaded" class="skeleton mt-4 h-16"></div>
    <ul v-else class="mt-4 divide-y divide-ink-800">
      <li v-for="row in rows" :key="row.id" class="flex items-center justify-between gap-4 py-3">
        <div class="min-w-0">
          <p class="truncate text-sm font-medium">
            {{ device(row.user_agent) }}
            <span
              v-if="row.current"
              class="ml-2 rounded bg-accent-500/15 px-1.5 py-0.5 text-xs font-normal text-accent-400"
            >
              This device
            </span>
          </p>
          <p class="mt-0.5 text-xs text-ink-400">
            {{ row.ip ?? "unknown IP" }} · active {{ ago(row.last_seen_at) }}
          </p>
        </div>
        <button
          v-if="!row.current"
          class="shrink-0 rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100 disabled:opacity-50"
          :disabled="busyId === row.id"
          @click="end(row)"
        >
          {{ busyId === row.id ? "Signing out…" : "Sign out" }}
        </button>
      </li>
    </ul>
  </section>
</template>
