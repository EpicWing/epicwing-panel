<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

interface Storage {
  enabled: boolean;
  endpoint: string;
  region: string;
  bucket: string;
  prefix: string;
  access_key: string;
  secret_key_set: boolean;
  path_style: boolean;
  keep_local: boolean;
  ready: boolean;
}

const PRESETS = [
  { id: "aws", label: "Amazon S3", endpoint: "https://s3.{region}.amazonaws.com", region: "eu-central-1", pathStyle: false },
  { id: "r2", label: "Cloudflare R2", endpoint: "https://ACCOUNT_ID.r2.cloudflarestorage.com", region: "auto", pathStyle: true },
  { id: "b2", label: "Backblaze B2", endpoint: "https://s3.{region}.backblazeb2.com", region: "eu-central-003", pathStyle: true },
  { id: "hetzner", label: "Hetzner Object Storage", endpoint: "https://{region}.your-objectstorage.com", region: "fsn1", pathStyle: true },
  { id: "wasabi", label: "Wasabi", endpoint: "https://s3.{region}.wasabisys.com", region: "eu-central-1", pathStyle: true },
  { id: "other", label: "Other (MinIO, Ceph, …)", endpoint: "", region: "auto", pathStyle: true },
];

const FIELD =
  "mt-1.5 w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-100 outline-none placeholder:text-ink-500 focus:border-accent-500";
const LABEL = "block text-sm font-medium text-ink-100";
const HINT = "mt-1 text-xs text-ink-400";

const loading = ref(true);
const saving = ref(false);
const testing = ref(false);
const error = ref("");
const notice = ref("");
const secretSet = ref(false);
const ready = ref(false);
const preset = ref("");
const result = ref<{ ok: boolean; detail: string } | null>(null);

const form = reactive({
  enabled: false,
  endpoint: "",
  region: "auto",
  bucket: "",
  prefix: "epicwing",
  access_key: "",
  secret_key: "",
  path_style: true,
  keep_local: false,
});

const state = computed(() => {
  if (ready.value) return { label: "Active", cls: "bg-ok/10 text-ok" };
  if (form.enabled) return { label: "Incomplete", cls: "bg-warn/10 text-warn" };
  return { label: "Off", cls: "bg-ink-800 text-ink-300" };
});

function apply(data: Storage): void {
  form.enabled = data.enabled;
  form.endpoint = data.endpoint;
  form.region = data.region;
  form.bucket = data.bucket;
  form.prefix = data.prefix;
  form.access_key = data.access_key;
  form.secret_key = "";
  form.path_style = data.path_style;
  form.keep_local = data.keep_local;
  secretSet.value = data.secret_key_set;
  ready.value = data.ready;
}

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "The server could not be reached.";
}

function usePreset(): void {
  const found = PRESETS.find((p) => p.id === preset.value);
  if (!found) return;
  form.region = found.region;
  form.endpoint = found.endpoint.replace("{region}", found.region);
  form.path_style = found.pathStyle;
}

async function load(): Promise<void> {
  try {
    apply(await api<Storage>("/admin/storage"));
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}

async function save(): Promise<void> {
  saving.value = true;
  error.value = "";
  notice.value = "";
  result.value = null;
  try {
    apply(
      await api<Storage>("/admin/storage", {
        method: "PUT",
        body: { ...form, secret_key: form.secret_key.trim() || null },
      }),
    );
    notice.value = "Saved.";
  } catch (cause) {
    error.value = message(cause);
  } finally {
    saving.value = false;
  }
}

async function test(): Promise<void> {
  testing.value = true;
  result.value = null;
  error.value = "";
  try {
    result.value = await api<{ ok: boolean; detail: string }>("/admin/storage/test", { method: "POST" });
  } catch (cause) {
    error.value = message(cause);
  } finally {
    testing.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <AppLayout title="Backup storage" subtitle="Keep backups in S3-compatible object storage." area="admin">
    <div class="space-y-5">
      <p v-if="error" role="alert" class="rounded-lg border border-bad/30 bg-bad/10 px-4 py-2.5 text-sm text-bad">{{ error }}</p>
      <p v-if="notice" role="status" class="rounded-lg border border-ok/30 bg-ok/10 px-4 py-2.5 text-sm text-ok">{{ notice }}</p>

      <div v-if="loading" class="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div class="skeleton h-96" />
        <div class="skeleton h-48" />
      </div>

      <div v-else class="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <form class="space-y-6 rounded-xl border border-ink-700 bg-ink-900 p-6" @submit.prevent="save">
          <div class="flex items-center justify-between gap-4">
            <label class="flex cursor-pointer items-center gap-3">
              <input v-model="form.enabled" type="checkbox" class="h-4 w-4 accent-accent-500" />
              <span class="text-sm font-medium text-ink-100">Store backups in object storage</span>
            </label>
            <span class="rounded-md px-2 py-0.5 text-xs font-medium" :class="state.cls">{{ state.label }}</span>
          </div>

          <div>
            <label :class="LABEL" for="s3-preset">Provider</label>
            <select id="s3-preset" v-model="preset" :class="FIELD" @change="usePreset">
              <option value="">Choose to fill in the endpoint …</option>
              <option v-for="item in PRESETS" :key="item.id" :value="item.id">{{ item.label }}</option>
            </select>
          </div>

          <div class="grid gap-5 sm:grid-cols-[minmax(0,1fr)_10rem]">
            <div>
              <label :class="LABEL" for="s3-endpoint">Endpoint</label>
              <input id="s3-endpoint" v-model="form.endpoint" type="text" placeholder="https://s3.eu-central-1.amazonaws.com" :class="FIELD + ' font-mono'" />
            </div>
            <div>
              <label :class="LABEL" for="s3-region">Region</label>
              <input id="s3-region" v-model="form.region" type="text" :class="FIELD + ' font-mono'" />
            </div>
          </div>

          <div class="grid gap-5 sm:grid-cols-2">
            <div>
              <label :class="LABEL" for="s3-bucket">Bucket</label>
              <input id="s3-bucket" v-model="form.bucket" type="text" :class="FIELD + ' font-mono'" />
            </div>
            <div>
              <label :class="LABEL" for="s3-prefix">Folder in the bucket</label>
              <input id="s3-prefix" v-model="form.prefix" type="text" :class="FIELD + ' font-mono'" />
            </div>
          </div>

          <div class="grid gap-5 sm:grid-cols-2">
            <div>
              <label :class="LABEL" for="s3-access">Access key</label>
              <input id="s3-access" v-model="form.access_key" type="text" autocomplete="off" :class="FIELD + ' font-mono'" />
            </div>
            <div>
              <label :class="LABEL" for="s3-secret">Secret key</label>
              <input id="s3-secret" v-model="form.secret_key" type="password" autocomplete="new-password" :placeholder="secretSet ? 'Saved, leave empty to keep it' : ''" :class="FIELD + ' font-mono'" />
            </div>
          </div>

          <div class="space-y-3 border-t border-ink-700 pt-5">
            <label class="flex cursor-pointer items-start gap-3">
              <input v-model="form.path_style" type="checkbox" class="mt-0.5 h-4 w-4 accent-accent-500" />
              <span>
                <span class="block text-sm text-ink-100">Path-style addresses</span>
                <span :class="HINT">endpoint/bucket/file instead of bucket.endpoint/file. Needed by R2, B2, MinIO and most others.</span>
              </span>
            </label>
            <label class="flex cursor-pointer items-start gap-3">
              <input v-model="form.keep_local" type="checkbox" class="mt-0.5 h-4 w-4 accent-accent-500" />
              <span>
                <span class="block text-sm text-ink-100">Keep a local copy on the node</span>
                <span :class="HINT">Faster restores, but uses disk space on the node. Off: the copy is deleted after the upload.</span>
              </span>
            </label>
          </div>

          <div class="flex gap-2">
            <button type="submit" :disabled="saving" class="rounded-lg bg-accent-500 px-5 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-40">
              {{ saving ? "Saving…" : "Save" }}
            </button>
          </div>
        </form>

        <aside class="space-y-4">
          <section class="rounded-xl border border-ink-700 bg-ink-900 p-5">
            <h3 class="text-sm font-semibold text-ink-100">Connection test</h3>
            <p class="mt-1 text-xs leading-5 text-ink-400">
              Uploads a small file, reads it through a temporary link like a node would, and deletes it. Save first.
            </p>
            <button
              class="mt-4 w-full rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-100 transition hover:border-ink-600 hover:bg-ink-800 disabled:opacity-40"
              :disabled="testing || !ready"
              @click="test"
            >
              {{ testing ? "Testing…" : "Test connection" }}
            </button>
            <p
              v-if="result"
              role="status"
              class="mt-3 rounded-lg px-3 py-2 text-xs"
              :class="result.ok ? 'bg-ok/10 text-ok' : 'bg-bad/10 text-bad'"
            >
              {{ result.detail }}
            </p>
          </section>

          <section class="rounded-xl border border-ink-700 bg-ink-900 p-5 text-xs leading-5 text-ink-400">
            <p class="font-semibold text-ink-200">How the keys are protected</p>
            <p class="mt-1">
              The keys stay in the panel, encrypted. Nodes never see them. They only get links for one file that expire
              after a few hours.
            </p>
            <p class="mt-3">Use a key that can only access this bucket.</p>
          </section>
        </aside>
      </div>
    </div>
  </AppLayout>
</template>
