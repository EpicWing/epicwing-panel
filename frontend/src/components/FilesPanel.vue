<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";

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
const MAX_LOAD = 5000;

const path = ref("");
const entries = ref<Entry[]>([]);
const total = ref(0);
const next = ref(-1);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const query = ref("");
const gutter = ref<HTMLElement | null>(null);

const editor = ref<{ path: string; content: string; original: string } | null>(null);
const saving = ref(false);

const blocked = computed(() => props.status === "new" || props.status === "installing");
const dirty = computed(() => editor.value !== null && editor.value.content !== editor.value.original);
const crumbs = computed(() => {
  const parts = path.value ? path.value.split("/") : [];
  return parts.map((name, index) => ({ name, path: parts.slice(0, index + 1).join("/") }));
});
const editorCrumbs = computed(() => {
  const parts = editor.value ? editor.value.path.split("/") : [];
  return parts.map((name, index) => ({
    name,
    path: parts.slice(0, index + 1).join("/"),
    last: index === parts.length - 1,
  }));
});
const lineNumbers = computed(() => {
  const count = editor.value ? editor.value.content.split("\n").length : 0;
  return Array.from({ length: count }, (_, index) => index + 1).join("\n");
});
const visible = computed(() => {
  const needle = query.value.trim().toLowerCase();
  const list = needle
    ? entries.value.filter((entry) => entry.name.toLowerCase().includes(needle))
    : entries.value;
  return [...list].sort((a, b) => {
    if (a.dir !== b.dir) return a.dir ? -1 : 1;
    return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
  });
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

function formatDate(seconds: number): string {
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - seconds));
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) {
    const hours = Math.floor(diff / 3600);
    return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  }
  if (diff < 7 * 86400) {
    const days = Math.floor(diff / 86400);
    return `${days} ${days === 1 ? "day" : "days"} ago`;
  }
  return new Date(seconds * 1000).toLocaleDateString([], {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function formatFull(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString();
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
    let all: Entry[] = offset > 0 ? [...entries.value] : [];
    let cursor = offset;
    let more = -1;
    let count = 0;
    for (;;) {
      const data = await api<Listing>(
        `${base()}?path=${encodeURIComponent(target)}&offset=${cursor}`,
      );
      if (token !== loadToken) return;
      all = all.concat(data.entries);
      count = data.total;
      more = data.next;
      if (more < 0 || all.length >= MAX_LOAD || data.entries.length === 0) break;
      cursor = more;
    }
    entries.value = all;
    total.value = count;
    next.value = more;
    if (target !== path.value) query.value = "";
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

function goTo(target: string): void {
  if (editor.value) {
    if (dirty.value && !window.confirm("Discard unsaved changes?")) return;
    editor.value = null;
  }
  void load(target);
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

function syncScroll(event: Event): void {
  if (gutter.value) gutter.value.scrollTop = (event.target as HTMLTextAreaElement).scrollTop;
}

function indent(event: KeyboardEvent): void {
  const area = event.target as HTMLTextAreaElement;
  if (!editor.value) return;
  const start = area.selectionStart;
  const end = area.selectionEnd;
  const value = editor.value.content;
  editor.value.content = `${value.slice(0, start)}  ${value.slice(end)}`;
  void nextTick(() => {
    area.selectionStart = start + 2;
    area.selectionEnd = start + 2;
  });
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
  <div class="space-y-5">
    <div v-if="!editor" class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-4xl font-bold">Files</h2>
        <p class="mt-2 text-sm text-ink-400">Browse and edit the files of your server.</p>
      </div>
      <div v-if="!blocked" class="flex gap-2">
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
        <nav class="flex min-w-0 flex-wrap items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-sm text-ink-300">
          <button class="rounded px-1.5 py-0.5 hover:bg-ink-800 hover:text-accent-300" @click="goTo('')">root</button>
          <template v-for="crumb in editorCrumbs" :key="crumb.path">
            <span class="text-ink-500">›</span>
            <span v-if="crumb.last" class="px-1.5 text-ink-100">{{ crumb.name }}<span v-if="dirty" class="ml-2 text-accent-300">● unsaved</span></span>
            <button v-else class="rounded px-1.5 py-0.5 hover:bg-ink-800 hover:text-accent-300" @click="goTo(crumb.path)">{{ crumb.name }}</button>
          </template>
        </nav>
        <div class="flex gap-2">
          <button class="rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-200 hover:bg-ink-800" @click="closeEditor">Close</button>
          <button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50" :disabled="saving || !dirty" @click="save">{{ saving ? "Saving…" : "Save" }}</button>
        </div>
      </div>
      <div class="flex overflow-hidden rounded-xl border border-ink-700 bg-ink-950 focus-within:border-accent-500" style="height: calc(100vh - 8.5rem); min-height: 24rem">
        <div ref="gutter" aria-hidden="true" class="shrink-0 select-none overflow-hidden border-r border-ink-800 bg-ink-900/60 py-4 pl-4 pr-3 text-right text-[13px] leading-6 text-ink-500">
          <pre class="m-0 pb-8 font-mono">{{ lineNumbers }}</pre>
        </div>
        <textarea
          v-model="editor.content"
          wrap="off"
          spellcheck="false"
          class="h-full min-w-0 flex-1 resize-none overflow-auto whitespace-pre bg-transparent px-4 py-4 font-mono text-[13px] leading-6 text-ink-100 focus:outline-none"
          @scroll="syncScroll"
          @keydown.ctrl.s.prevent="save"
          @keydown.tab.prevent="indent"
        ></textarea>
      </div>
    </div>

    <div v-else class="space-y-3">
      <nav class="flex flex-wrap items-center gap-1 rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 font-mono text-sm text-ink-300">
        <button v-if="path" class="rounded px-1.5 py-0.5 hover:bg-ink-800 hover:text-accent-300" @click="goTo('')">root</button>
        <span v-else class="px-1.5 text-ink-100">root</span>
        <template v-for="(crumb, index) in crumbs" :key="crumb.path">
          <span class="text-ink-500">›</span>
          <span v-if="index === crumbs.length - 1" class="px-1.5 text-ink-100">{{ crumb.name }}</span>
          <button v-else class="rounded px-1.5 py-0.5 hover:bg-ink-800 hover:text-accent-300" @click="goTo(crumb.path)">{{ crumb.name }}</button>
        </template>
      </nav>

      <div class="relative">
        <svg class="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input v-model="query" type="search" placeholder="Search…" class="w-full rounded-xl border border-ink-700 bg-ink-900 py-3 pl-11 pr-4 text-sm text-ink-100 placeholder:text-ink-500 focus:border-accent-500 focus:outline-none" />
      </div>

      <div class="space-y-2">
        <div v-if="path" class="flex cursor-pointer items-center gap-3 rounded-xl border border-ink-800 bg-ink-900 px-4 py-3 text-sm text-ink-300 hover:border-ink-600 hover:bg-ink-800/60" @click="goUp">
          <svg class="h-5 w-5 shrink-0 text-ink-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14 4 9l5-5"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/></svg>
          <span>Back</span>
        </div>

        <div
          v-for="entry in visible"
          :key="entry.name"
          class="group grid cursor-pointer grid-cols-[minmax(0,1fr)_7rem_9rem_auto] items-center gap-4 rounded-xl border border-ink-800 bg-ink-900 px-4 py-3 text-sm hover:border-ink-600 hover:bg-ink-800/60"
          @click="activate(entry)"
        >
          <div class="flex min-w-0 items-center gap-3">
            <svg v-if="entry.dir" class="h-5 w-5 shrink-0 text-accent-500" viewBox="0 0 24 24" fill="currentColor"><path d="M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2z"/></svg>
            <svg v-else class="h-5 w-5 shrink-0 text-ink-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>
            <span class="truncate font-medium text-ink-100">{{ entry.name }}</span>
            <span v-if="entry.link" class="shrink-0 rounded bg-ink-800 px-1.5 py-0.5 text-xs text-ink-400">link</span>
          </div>
          <span class="text-right text-ink-400">{{ entry.dir ? "—" : formatBytes(entry.size) }}</span>
          <span class="text-right text-ink-400" :title="formatFull(entry.mtime)">{{ formatDate(entry.mtime) }}</span>
          <div class="flex justify-end gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
            <button class="rounded px-2 py-1 text-ink-300 hover:bg-ink-700 hover:text-ink-100 disabled:opacity-50" :disabled="busy" @click.stop="rename(entry)">Rename</button>
            <button class="rounded px-2 py-1 text-bad hover:bg-ink-700 disabled:opacity-50" :disabled="busy" @click.stop="remove(entry)">Delete</button>
          </div>
        </div>

        <p v-if="!loading && !error && visible.length === 0" class="py-12 text-center text-sm text-ink-500">{{ query ? "No matches." : "This folder is empty." }}</p>
      </div>

      <div class="flex items-center justify-between text-sm text-ink-400">
        <span>{{ loading ? "Loading…" : query ? `${visible.length} matches` : `${entries.length} of ${total} entries` }}</span>
        <button v-if="next >= 0" class="rounded-lg border border-ink-700 px-4 py-2 text-ink-200 hover:bg-ink-800 disabled:opacity-50" :disabled="loading" @click="load(path, next)">Load more</button>
      </div>
    </div>
  </div>
</template>
