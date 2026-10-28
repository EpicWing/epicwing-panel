<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";

import { ApiError, api } from "../api/client";

interface Entry {
  name: string;
  dir: boolean;
  link: boolean;
  size: number;
  mtime: number;
}

interface Listing {
  entries: Entry[];
  total: number;
  next: number;
}

interface ReadChunk {
  data: string;
  size: number;
  eof: boolean;
}

const props = defineProps<{ serverId: string; status: string }>();

const CHUNK = 8 * 1024;
const MAX_EDIT = 1024 * 1024;

const path = ref("");
const entries = ref<Entry[]>([]);
const total = ref(0);
const next = ref(-1);
const loading = ref(false);
const busy = ref(false);
const error = ref("");

const editor = ref<{ path: string; content: string; original: string } | null>(null);
const saving = ref(false);

const blocked = computed(() => props.status === "new" || props.status === "installing");
const dirty = computed(() => editor.value !== null && editor.value.content !== editor.value.original);
const crumbs = computed(() => {
  const parts = path.value ? path.value.split("/") : [];
  return parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join("/") }));
});

function base(): string {
  return `/servers/${props.serverId}/files`;
}

function join(dir: string, name: string): string {
  return dir ? `${dir}/${name}` : name;
}

function fail(cause: unknown): void {
  error.value = cause instanceof ApiError ? cause.message : "The panel is unreachable.";
}

function formatBytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount >= 10 || unit === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unit]}`;
}

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function validName(name: string): boolean {
  return name !== "" && name !== "." && name !== ".." && !name.includes("/") && !name.includes("\0");
}

let loadToken = 0;

async function load(target: string, offset = 0): Promise<void> {
  const token = ++loadToken;
  loading.value = true;
  error.value = "";
  try {
    const data = await api<Listing>(
      `${base()}?path=${encodeURIComponent(target)}&offset=${offset}`,
    );
    if (token !== loadToken) return;
    entries.value = offset > 0 ? [...entries.value, ...data.entries] : data.entries;
    total.value = data.total;
    next.value = data.next;
    path.value = target;
  } catch (cause) {
    if (token === loadToken) fail(cause);
  } finally {
    if (token === loadToken) loading.value = false;
  }
}

function goUp(): void {
  const index = path.value.lastIndexOf("/");
  void load(index === -1 ? "" : path.value.slice(0, index));
}

async function openFile(entry: Entry): Promise<void> {
  if (entry.size > MAX_EDIT) {
    error.value = "This file is too large for the editor (limit 1 MiB).";
    return;
  }
  const target = join(path.value, entry.name);
  error.value = "";
  busy.value = true;
  try {
    const parts: Uint8Array[] = [];
    let offset = 0;
    for (;;) {
      const chunk = await api<ReadChunk>(
        `${base()}/content?path=${encodeURIComponent(target)}&offset=${offset}&length=${CHUNK}`,
      );
      const bytes = fromBase64(chunk.data);
      parts.push(bytes);
      offset += bytes.length;
      if (offset > MAX_EDIT) {
        error.value = "This file is too large for the editor (limit 1 MiB).";
        return;
      }
      if (chunk.eof || bytes.length === 0) break;
    }
    const all = new Uint8Array(offset);
    let position = 0;
    for (const part of parts) {
      all.set(part, position);
      position += part.length;
    }
    if (all.includes(0)) {
      error.value = "Binary files cannot be opened in the editor.";
      return;
    }
    let text: string;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(all);
    } catch {
      error.value = "This file is not valid UTF-8 and cannot be edited here.";
      return;
    }
    editor.value = { path: target, content: text, original: text };
  } catch (cause) {
    fail(cause);
  } finally {
    busy.value = false;
  }
}

async function save(): Promise<void> {
  if (!editor.value || saving.value) return;
  const target = editor.value.path;
  const content = editor.value.content;
  const bytes = new TextEncoder().encode(content);
  saving.value = true;
  error.value = "";
  try {
    const url = `${base()}/content`;
    if (bytes.length === 0) {
      await api(url, { method: "PUT", body: { path: target, offset: 0, data: "", create: true, truncate: true } });
    }
    for (let offset = 0; offset < bytes.length; offset += CHUNK) {
      await api(url, {
        method: "PUT",
        body: {
          path: target,
          offset,
          data: toBase64(bytes.subarray(offset, offset + CHUNK)),
          create: offset === 0,
          truncate: offset === 0,
        },
      });
    }
    if (editor.value) editor.value.original = content;
  } catch (cause) {
    fail(cause);
  } finally {
    saving.value = false;
  }
}

function closeEditor(): void {
  if (dirty.value && !window.confirm("Discard unsaved changes?")) return;
  editor.value = null;
  void load(path.value);
}

function activate(entry: Entry): void {
  if (entry.dir) void load(join(path.value, entry.name));
  else void openFile(entry);
}

async function action(call: () => Promise<unknown>): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    await call();
    await load(path.value);
  } catch (cause) {
    fail(cause);
  } finally {
    busy.value = false;
  }
}

function exists(name: string): boolean {
  return entries.value.some((entry) => entry.name === name);
}

async function newFile(): Promise<void> {
  const name = window.prompt("Name of the new file")?.trim();
  if (name === undefined) return;
  if (!validName(name)) {
    error.value = "Invalid name.";
    return;
  }
  if (exists(name)) {
    error.value = "A file with this name already exists.";
    return;
  }
  await action(() =>
    api(`${base()}/content`, {
      method: "PUT",
      body: { path: join(path.value, name), offset: 0, data: "", create: true, truncate: false },
    }),
  );
}

async function newFolder(): Promise<void> {
  const name = window.prompt("Name of the new folder")?.trim();
  if (name === undefined) return;
  if (!validName(name)) {
    error.value = "Invalid name.";
    return;
  }
  await action(() =>
    api(`${base()}/folder`, { method: "POST", body: { path: join(path.value, name) } }),
  );
}

async function rename(entry: Entry): Promise<void> {
  const name = window.prompt("New name", entry.name)?.trim();
  if (name === undefined || name === entry.name) return;
  if (!validName(name)) {
    error.value = "Invalid name.";
    return;
  }
  await action(() =>
    api(`${base()}/rename`, {
      method: "POST",
      body: { path: join(path.value, entry.name), to: join(path.value, name) },
    }),
  );
}

async function remove(entry: Entry): Promise<void> {
  const what = entry.dir ? `the folder "${entry.name}" and everything in it` : `"${entry.name}"`;
  if (!window.confirm(`Delete ${what}? This cannot be undone.`)) return;
  await action(() =>
    api(`${base()}/delete`, {
      method: "POST",
      body: { path: join(path.value, entry.name), recursive: entry.dir },
    }),
  );
}

onMounted(() => {
  if (!blocked.value) void load("");
});

watch(blocked, (value) => {
  if (!value) void load("");
});
</script>

<template>
  <div class="space-y-6">
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-4xl font-bold">Files</h2>
        <p class="mt-2 text-sm text-ink-400">Browse and edit the files of your server.</p>
      </div>
      <div v-if="!blocked && !editor" class="flex gap-2">
        <button class="rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-200 hover:bg-ink-800 disabled:opacity-50" :disabled="busy" @click="newFolder">New Folder</button>
        <button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50" :disabled="busy" @click="newFile">New File</button>
      </div>
    </div>

    <p v-if="error" class="rounded-lg border border-bad/50 px-4 py-3 text-sm text-bad">{{ error }}</p>

    <div v-if="blocked" class="flex min-h-[16rem] items-center justify-center rounded-xl border border-ink-700 bg-ink-900 text-center">
      <p class="text-sm text-ink-400">Files are available once the installation has finished.</p>
    </div>

    <div v-else-if="editor" class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="font-mono text-sm text-ink-200">{{ editor.path }}<span v-if="dirty" class="ml-2 text-ink-400">(unsaved)</span></p>
        <div class="flex gap-2">
          <button class="rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-200 hover:bg-ink-800" @click="closeEditor">Close</button>
          <button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50" :disabled="saving || !dirty" @click="save">{{ saving ? "Saving…" : "Save" }}</button>
        </div>
      </div>
      <textarea
        v-model="editor.content"
        spellcheck="false"
        class="h-[32rem] w-full resize-y rounded-xl border border-ink-700 bg-ink-950 p-4 font-mono text-sm text-ink-100"
        @keydown.ctrl.s.prevent="save"
      ></textarea>
    </div>

    <div v-else class="space-y-3">
      <nav class="flex flex-wrap items-center gap-1 text-sm text-ink-300">
        <button class="hover:text-accent-300" @click="load('')">root</button>
        <template v-for="crumb in crumbs" :key="crumb.path">
          <span class="text-ink-500">/</span>
          <button class="hover:text-accent-300" @click="load(crumb.path)">{{ crumb.name }}</button>
        </template>
      </nav>

      <div class="overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
        <table class="w-full text-left text-sm">
          <thead class="text-ink-400">
            <tr>
              <th class="px-4 py-2 font-medium">Name</th>
              <th class="px-4 py-2 font-medium">Size</th>
              <th class="px-4 py-2 font-medium">Modified</th>
              <th class="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="path" class="border-t border-ink-800 hover:bg-ink-800/50">
              <td class="px-4 py-2" colspan="4"><button class="text-ink-300 hover:text-accent-300" @click="goUp">..</button></td>
            </tr>
            <tr v-for="entry in entries" :key="entry.name" class="border-t border-ink-800 hover:bg-ink-800/50">
              <td class="px-4 py-2">
                <button class="text-left text-ink-100 hover:text-accent-300" @click="activate(entry)">{{ entry.name }}{{ entry.dir ? "/" : "" }}</button>
                <span v-if="entry.link" class="ml-2 text-xs text-ink-500">link</span>
              </td>
              <td class="px-4 py-2 text-ink-400">{{ entry.dir ? "—" : formatBytes(entry.size) }}</td>
              <td class="px-4 py-2 text-ink-400">{{ new Date(entry.mtime * 1000).toLocaleString() }}</td>
              <td class="px-4 py-2 text-right">
                <button class="mr-3 text-ink-300 hover:text-accent-300 disabled:opacity-50" :disabled="busy" @click="rename(entry)">Rename</button>
                <button class="text-bad disabled:opacity-50" :disabled="busy" @click="remove(entry)">Delete</button>
              </td>
            </tr>
            <tr v-if="!loading && !error && entries.length === 0">
              <td class="px-4 py-10 text-center text-ink-500" colspan="4">This folder is empty.</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex items-center justify-between text-sm text-ink-400">
        <span>{{ loading ? "Loading…" : `${entries.length} of ${total} entries` }}</span>
        <button v-if="next >= 0" class="rounded-lg border border-ink-700 px-4 py-2 text-ink-200 hover:bg-ink-800 disabled:opacity-50" :disabled="loading" @click="load(path, next)">Load more</button>
      </div>
    </div>
  </div>
</template>
