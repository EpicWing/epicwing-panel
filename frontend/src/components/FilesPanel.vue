<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { ApiError, api } from "../api/client";
import { buildZip, type ZipItem } from "../lib/zip";
import { LANGUAGES, detectLanguage, highlight, type Lang } from "../lib/highlight";

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

interface Item {
  name: string;
  full: string;
  size: number;
  mtime: number;
  dir: boolean;
}

class LocalError extends Error {}

const props = defineProps<{ serverId: string; status: string }>();

const CHUNK = 8 * 1024;
const MAX_EDIT = 1024 * 1024;
const MAX_LOAD = 5000;
const MAX_FILES = 5000;
const MAX_TRANSFER = 100 * 1024 * 1024;

const path = ref("");
const entries = ref<Entry[]>([]);
const total = ref(0);
const next = ref(-1);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const query = ref("");
const progress = ref("");
const selected = ref<string[]>([]);
const menu = ref<string | null>(null);
const gutter = ref<HTMLElement | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const backdrop = ref<HTMLElement | null>(null);
const language = ref<Lang>("plain");

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
const selectedEntries = computed(() =>
  visible.value.filter((entry) => selected.value.includes(entry.name)),
);
const allSelected = computed(
  () => visible.value.length > 0 && selectedEntries.value.length === visible.value.length,
);
const downloadLabel = computed(() => {
  const [only] = selectedEntries.value;
  return selectedEntries.value.length === 1 && only && !only.dir ? "Download" : "Download ZIP";
});

const HIGHLIGHT_LIMIT = 256 * 1024;
const overlay = computed(
  () =>
    editor.value !== null &&
    language.value !== "plain" &&
    editor.value.content.length <= HIGHLIGHT_LIMIT,
);
const highlighted = computed(() =>
  editor.value && overlay.value ? highlight(editor.value.content, language.value) : "",
);

function base(): string {
  return `/servers/${props.serverId}/files`;
}

function join(dir: string, name: string): string {
  return dir ? `${dir}/${name}` : name;
}

function fail(cause: unknown): void {
  error.value =
    cause instanceof ApiError || cause instanceof LocalError
      ? cause.message
      : "The panel is unreachable.";
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

async function readFile(target: string, limit: number) {
  const parts: Uint8Array[] = [];
  let offset = 0;
  for (;;) {
    const chunk = await api<ReadChunk>(
      `${base()}/content?path=${encodeURIComponent(target)}&offset=${offset}&length=${CHUNK}`,
    );
    const bytes = fromBase64(chunk.data);
    parts.push(bytes);
    offset += bytes.length;
    if (offset > limit) throw new LocalError(`The file is larger than ${formatBytes(limit)}.`);
    if (chunk.eof || bytes.length === 0) break;
  }
  const all = new Uint8Array(offset);
  let position = 0;
  for (const part of parts) {
    all.set(part, position);
    position += part.length;
  }
  return all;
}

async function writeFile(
  target: string,
  bytes: Uint8Array,
  report?: (done: number) => void,
): Promise<void> {
  const url = `${base()}/content`;
  if (bytes.length === 0) {
    await api(url, { method: "PUT", body: { path: target, offset: 0, data: "", create: true, truncate: true } });
    return;
  }
  for (let offset = 0; offset < bytes.length; offset += CHUNK) {
    report?.(offset);
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
}

async function listAll(dir: string): Promise<Entry[]> {
  let all: Entry[] = [];
  let cursor = 0;
  for (;;) {
    const data = await api<Listing>(
      `${base()}?path=${encodeURIComponent(dir)}&offset=${cursor}`,
    );
    all = all.concat(data.entries);
    if (data.next < 0 || data.entries.length === 0) return all;
    cursor = data.next;
  }
}

async function walk(entry: Entry, dir: string, prefix: string, out: Item[]): Promise<void> {
  const full = join(dir, entry.name);
  const name = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (out.length > MAX_FILES) throw new LocalError(`More than ${MAX_FILES} files selected.`);
  if (!entry.dir) {
    out.push({ name, full, size: entry.size, mtime: entry.mtime, dir: false });
    return;
  }
  if (entry.link) return;
  const children = await listAll(full);
  if (children.length === 0) out.push({ name, full, size: 0, mtime: entry.mtime, dir: true });
  for (const child of children) await walk(child, full, name, out);
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
    if (target !== path.value) {
      query.value = "";
      selected.value = [];
    } else {
      const names = new Set(all.map((entry) => entry.name));
      selected.value = selected.value.filter((name) => names.has(name));
    }
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

function toggle(name: string): void {
  selected.value = selected.value.includes(name)
    ? selected.value.filter((entry) => entry !== name)
    : [...selected.value, name];
}

function toggleMenu(name: string): void {
  menu.value = menu.value === name ? null : name;
}

function closeMenu(): void {
  menu.value = null;
}

function toggleAll(): void {
  selected.value = allSelected.value ? [] : visible.value.map((entry) => entry.name);
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
    const all = await readFile(target, MAX_EDIT);
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
    language.value = detectLanguage(entry.name, text);
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
  saving.value = true;
  error.value = "";
  try {
    await writeFile(target, new TextEncoder().encode(content));
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
  const area = event.target as HTMLTextAreaElement;
  if (gutter.value) gutter.value.scrollTop = area.scrollTop;
  if (backdrop.value) {
    backdrop.value.scrollTop = area.scrollTop;
    backdrop.value.scrollLeft = area.scrollLeft;
  }
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
  let failure: unknown = null;
  try {
    await call();
  } catch (cause) {
    failure = cause;
  }
  await load(path.value);
  if (failure) fail(failure);
  busy.value = false;
}

function exists(name: string): boolean {
  return entries.value.some((entry) => entry.name === name);
}

interface Dialog {
  kind: "file" | "folder" | "rename" | "move" | "moveMany" | "delete";
  entries: Entry[];
  value: string;
}

const DIALOGS = {
  file: { title: "New file", label: "File name", hint: "Enter the name of the new file.", submit: "Create file" },
  folder: { title: "New folder", label: "Folder name", hint: "Enter the name of the new folder.", submit: "Create folder" },
  rename: { title: "Rename", label: "New name or path", hint: "A path such as plugins/name.dll moves the item.", submit: "Rename" },
  move: { title: "Move", label: "New name or path", hint: "Relative to the current folder, a leading / starts at the root.", submit: "Move" },
  delete: { title: "Delete", label: "", hint: "This cannot be undone.", submit: "Delete" },
  moveMany: { title: "Move items", label: "Destination folder", hint: "Relative to the current folder, a leading / starts at the root.", submit: "Move" },
} as const;

const dialog = ref<Dialog | null>(null);
const dialogError = ref("");
const dialogInput = ref<HTMLInputElement | null>(null);
const dialogText = computed(() => (dialog.value ? DIALOGS[dialog.value.kind] : null));
const dialogPreview = computed(() => {
  const d = dialog.value;
  if (!d || d.kind === "file" || d.kind === "folder" || d.kind === "delete") return "";
  const target = resolveTarget(d.value.trim());
  if (target === null) return "";
  if (d.kind === "moveMany") return `/${target}`;
  return target === "" ? "" : `/${target}`;
});

const dialogSubmit = ref<HTMLButtonElement | null>(null);
const deleteText = computed(() => {
  const d = dialog.value;
  if (!d || d.kind !== "delete") return "";
  const folders = d.entries.some((entry) => entry.dir);
  const count = d.entries.length;
  const what = count === 1 ? "this item" : `these ${count} items`;
  return folders ? `Delete ${what}? Folders are deleted with everything in them.` : `Delete ${what}?`;
});

function openDialog(kind: Dialog["kind"], entries: Entry[] = [], value = ""): void {
  if (busy.value) return;
  if (kind !== "file" && kind !== "folder" && entries.length === 0) return;
  dialogError.value = "";
  dialog.value = { kind, entries, value };
  void nextTick(() => {
    if (kind === "delete") {
      dialogSubmit.value?.focus();
      return;
    }
    dialogInput.value?.focus();
    dialogInput.value?.select();
  });
}

function closeDialog(): void {
  dialog.value = null;
}

async function submitDialog(): Promise<void> {
  const d = dialog.value;
  if (!d || busy.value) return;
  const value = d.value.trim();
  dialogError.value = "";

  if (d.kind === "file" || d.kind === "folder") {
    if (!validName(value)) {
      dialogError.value = "Enter a valid name without slashes.";
      return;
    }
    if (exists(value)) {
      dialogError.value = "An item with this name already exists.";
      return;
    }
    closeDialog();
    const target = join(path.value, value);
    if (d.kind === "file") {
      await action(() =>
        api(`${base()}/content`, {
          method: "PUT",
          body: { path: target, offset: 0, data: "", create: true, truncate: false },
        }),
      );
    } else {
      await action(() => api(`${base()}/folder`, { method: "POST", body: { path: target } }));
    }
    return;
  }

  if (d.kind === "moveMany") {
    const dest = resolveTarget(value);
    if (dest === null) {
      dialogError.value = "Invalid folder.";
      return;
    }
    if (dest === path.value) {
      dialogError.value = "The items are already in this folder.";
      return;
    }
    const targets = d.entries;
    closeDialog();
    selected.value = [];
    await action(async () => {
      const failed: string[] = [];
      let reason = "";
      for (const entry of targets) {
        const from = join(path.value, entry.name);
        if (entry.dir && (dest === from || dest.startsWith(`${from}/`))) {
          failed.push(entry.name);
          reason = reason || "A folder cannot be moved into itself.";
          continue;
        }
        try {
          await api(`${base()}/rename`, {
            method: "POST",
            body: { path: from, to: join(dest, entry.name) },
          });
        } catch (cause) {
          failed.push(entry.name);
          if (!reason && cause instanceof Error) reason = cause.message;
        }
      }
      if (failed.length > 0) {
        throw new LocalError(`Could not move ${failed.join(", ")}${reason ? `: ${reason}` : ""}`);
      }
    });
    return;
  }

  if (d.kind === "delete") {
    const targets = d.entries;
    closeDialog();
    selected.value = [];
    await action(async () => {
      const failed: string[] = [];
      let reason = "";
      for (const entry of targets) {
        try {
          await api(`${base()}/delete`, {
            method: "POST",
            body: { path: join(path.value, entry.name), recursive: entry.dir },
          });
        } catch (cause) {
          failed.push(entry.name);
          if (!reason && cause instanceof Error) reason = cause.message;
        }
      }
      if (failed.length > 0) {
        throw new LocalError(`Could not delete ${failed.join(", ")}${reason ? `: ${reason}` : ""}`);
      }
    });
    return;
  }

  const entry = d.entries[0];
  if (!entry) return;
  const from = join(path.value, entry.name);
  const to = value === "" ? null : resolveTarget(value);
  if (to === null || to === "") {
    dialogError.value = "Enter a valid name or path.";
    return;
  }
  if (to === from) {
    dialogError.value = "That is the current name.";
    return;
  }
  if (entry.dir && to.startsWith(`${from}/`)) {
    dialogError.value = "A folder cannot be moved into itself.";
    return;
  }
  closeDialog();
  await action(() => api(`${base()}/rename`, { method: "POST", body: { path: from, to } }));
}

// Löst eine Eingabe relativ zum aktuellen Ordner auf, ein führendes "/" meint die Wurzel.
function resolveTarget(input: string): string | null {
  const parts = input.startsWith("/") || !path.value ? [] : path.value.split("/");
  for (const part of input.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") {
      if (parts.length === 0) return null;
      parts.pop();
    } else if (part.includes("\0")) {
      return null;
    } else {
      parts.push(part);
    }
  }
  return parts.join("/");
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

async function download(targets: Entry[]): Promise<void> {
  if (busy.value || targets.length === 0) return;
  busy.value = true;
  error.value = "";
  try {
    const [only] = targets;
    if (targets.length === 1 && only && !only.dir) {
      const link = document.createElement("a");
      link.href = `/api${base()}/download?path=${encodeURIComponent(join(path.value, only.name))}`;
      link.download = only.name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      return;
    }

    progress.value = "Collecting files…";
    const items: Item[] = [];
    for (const entry of targets) await walk(entry, path.value, "", items);
    const bytes = items.reduce((sum, item) => sum + item.size, 0);
    if (bytes > MAX_TRANSFER) {
      throw new LocalError(
        `The selection is ${formatBytes(bytes)}. Browser downloads are limited to ${formatBytes(MAX_TRANSFER)} for now.`,
      );
    }
    const files: ZipItem[] = [];
    for (const item of items) {
      progress.value = `Reading ${files.length + 1} / ${items.length}: ${item.name}`;
      const data = item.dir ? new Uint8Array(0) : await readFile(item.full, MAX_TRANSFER);
      files.push({ name: item.name, data, mtime: item.mtime, dir: item.dir });
    }
    const [first] = targets;
    const folder = path.value.split("/").pop() || "files";
    const filename = targets.length === 1 && first ? `${first.name}.zip` : `${folder}.zip`;
    saveBlob(buildZip(files), filename);
  } catch (cause) {
    fail(cause);
  } finally {
    progress.value = "";
    busy.value = false;
  }
}

async function upload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const files = input.files ? Array.from(input.files) : [];
  input.value = "";
  if (files.length === 0 || busy.value) return;
  const clashes = files.filter((file) => exists(file.name)).map((file) => file.name);
  if (clashes.length > 0 && !window.confirm(`Overwrite ${clashes.join(", ")}?`)) return;
  busy.value = true;
  error.value = "";
  let failure: unknown = null;
  try {
    let number = 0;
    for (const file of files) {
      number += 1;
      if (!validName(file.name)) throw new LocalError(`Invalid file name: ${file.name}`);
      if (file.size > MAX_TRANSFER) {
        throw new LocalError(`"${file.name}" is larger than ${formatBytes(MAX_TRANSFER)}.`);
      }
      const bytes = new Uint8Array(await file.arrayBuffer());
      await writeFile(join(path.value, file.name), bytes, (done) => {
        const percent = Math.floor((done / bytes.length) * 100);
        progress.value = `Uploading ${file.name} (${number}/${files.length}) ${percent}%`;
      });
    }
  } catch (cause) {
    failure = cause;
  }
  progress.value = "";
  await load(path.value);
  if (failure) fail(failure);
  busy.value = false;
}

onMounted(() => {
  document.addEventListener("click", closeMenu);
  if (!blocked.value) void load("");
});

onBeforeUnmount(() => document.removeEventListener("click", closeMenu));

watch(blocked, (value) => {
  if (!value) void load("");
});
</script>

<template>
  <div class="min-w-0 space-y-4">
    <div v-if="!editor" class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h2 class="text-4xl font-bold">Files</h2>
        <p class="mt-2 text-sm text-ink-400">Browse and edit the files of your server.</p>
      </div>
      <div v-if="!blocked" class="flex gap-2">
        <button class="rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-200 hover:bg-ink-800 disabled:opacity-50" :disabled="busy" @click="openDialog('folder')">New Folder</button>
        <button class="rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-200 hover:bg-ink-800 disabled:opacity-50" :disabled="busy" @click="openDialog('file')">New File</button>
        <button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50" :disabled="busy" @click="fileInput?.click()">Upload</button>
        <input ref="fileInput" type="file" multiple class="hidden" @change="upload" />
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
          <select v-model="language" title="Language" class="rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm text-ink-200 focus:border-accent-500 focus:outline-none">
            <option v-for="item in LANGUAGES" :key="item.id" :value="item.id">{{ item.label }}</option>
          </select>
          <button class="rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-200 hover:bg-ink-800" @click="closeEditor">Close</button>
          <button class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 disabled:opacity-50" :disabled="saving || !dirty" @click="save">{{ saving ? "Saving…" : "Save" }}</button>
        </div>
      </div>
      <div class="code-surface flex overflow-hidden rounded-xl border border-ink-700 focus-within:border-accent-500" style="height: calc(100vh - 8.5rem); min-height: 24rem">
        <div ref="gutter" aria-hidden="true" class="code code-gutter shrink-0 select-none overflow-hidden border-r border-ink-800 py-3 pl-4 pr-3 text-right">
          <pre class="code m-0 pb-8">{{ lineNumbers }}</pre>
        </div>
        <div class="relative min-w-0 flex-1">
          <div v-if="overlay" ref="backdrop" aria-hidden="true" class="pointer-events-none absolute inset-0 overflow-hidden px-4 py-3">
            <pre class="code code-layer m-0 pb-8 pr-8" v-html="highlighted"></pre>
          </div>
          <textarea
            v-model="editor.content"
            wrap="off"
            spellcheck="false"
            class="code code-input absolute inset-0 h-full w-full resize-none overflow-auto whitespace-pre bg-transparent px-4 py-3 focus:outline-none"
            :class="overlay ? 'code-input--overlay' : 'text-ink-100'"
            @scroll="syncScroll"
            @keydown.ctrl.s.prevent="save"
            @keydown.tab.prevent="indent"
          ></textarea>
        </div>
      </div>
    </div>

    <div v-else class="space-y-3">
      <div class="flex items-center gap-3 px-3">
        <input type="checkbox" class="h-4 w-4 shrink-0 cursor-pointer accent-accent-500" title="Select all" :checked="allSelected" :disabled="visible.length === 0" @change="toggleAll" />
        <nav class="flex min-w-0 flex-wrap items-center gap-1 text-sm text-ink-300">
          <button v-if="path" class="rounded px-1.5 py-0.5 hover:bg-ink-800 hover:text-accent-400" @click="goTo('')">root</button>
          <span v-else class="px-1.5 font-medium text-ink-100">root</span>
          <template v-for="(crumb, index) in crumbs" :key="crumb.path">
            <span class="text-ink-400">›</span>
            <span v-if="index === crumbs.length - 1" class="px-1.5 font-medium text-ink-100">{{ crumb.name }}</span>
            <button v-else class="rounded px-1.5 py-0.5 hover:bg-ink-800 hover:text-accent-400" @click="goTo(crumb.path)">{{ crumb.name }}</button>
          </template>
        </nav>
      </div>

      <div class="rounded-xl border border-ink-800 bg-ink-900/60 p-1.5">
        <div class="relative">
          <svg class="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
          <input v-model="query" type="search" placeholder="Search…" class="w-full rounded-lg border border-transparent bg-ink-950 py-3 pl-11 pr-4 text-sm font-medium text-ink-100 placeholder:text-ink-400 focus:border-accent-500 focus:outline-none" />
        </div>

        <div class="mt-1.5 space-y-1">
          <div v-if="path" class="grid cursor-pointer grid-cols-[1.5rem_minmax(0,1fr)] items-center gap-3 rounded-lg bg-ink-950 px-3 py-2.5 text-sm text-ink-300 hover:bg-ink-800/70" @click="goUp">
            <svg class="h-5 w-5 text-ink-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14 4 9l5-5"/><path d="M20 20v-7a4 4 0 0 0-4-4H4"/></svg>
            <span>Back</span>
          </div>

          <div
            v-for="entry in visible"
            :key="entry.name"
            class="group grid cursor-pointer grid-cols-[1.5rem_minmax(0,1fr)_2rem] items-center gap-3 rounded-lg px-3 py-2.5 text-sm sm:grid-cols-[1.5rem_minmax(0,1fr)_6rem_10rem_2rem]"
            :class="selected.includes(entry.name) ? 'bg-ink-800 ring-1 ring-inset ring-accent-500/50' : 'bg-ink-950 hover:bg-ink-800/70'"
            @click="activate(entry)"
          >
            <label class="flex items-center" @click.stop>
              <input type="checkbox" class="h-4 w-4 cursor-pointer accent-accent-500" :checked="selected.includes(entry.name)" @change="toggle(entry.name)" />
            </label>
            <div class="flex min-w-0 items-center gap-3">
              <svg v-if="entry.dir" class="h-5 w-5 shrink-0 text-accent-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>
              <svg v-else class="h-5 w-5 shrink-0 text-ink-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/></svg>
              <span class="truncate font-semibold text-ink-100">{{ entry.name }}</span>
              <span v-if="entry.link" class="shrink-0 rounded bg-ink-700 px-1.5 py-0.5 text-xs text-ink-300">link</span>
            </div>
            <span class="hidden text-right text-ink-400 sm:block">{{ entry.dir ? "—" : formatBytes(entry.size) }}</span>
            <span class="hidden text-right text-ink-400 sm:block" :title="formatFull(entry.mtime)">{{ formatDate(entry.mtime) }}</span>
            <div class="relative flex justify-end" @click.stop>
              <button type="button" class="flex h-8 w-8 items-center justify-center rounded-md text-ink-400 hover:bg-ink-700 hover:text-ink-100 disabled:opacity-50" :class="menu === entry.name ? 'bg-ink-700 text-ink-100' : ''" :disabled="busy" aria-label="Actions" aria-haspopup="menu" :aria-expanded="menu === entry.name" @click="toggleMenu(entry.name)">
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="12" cy="19" r="1.6"/></svg>
              </button>
              <div v-if="menu === entry.name" role="menu" class="absolute right-0 top-full z-30 mt-1 w-44 rounded-lg border border-ink-700 bg-ink-900 py-1 text-sm shadow-2xl">
                <button role="menuitem" class="block w-full px-3 py-2 text-left text-ink-100 hover:bg-ink-800" @click="closeMenu(); download([entry])">{{ entry.dir ? "Download ZIP" : "Download" }}</button>
                <button role="menuitem" class="block w-full px-3 py-2 text-left text-ink-100 hover:bg-ink-800" @click="closeMenu(); openDialog('rename', [entry], entry.name)">Rename</button>
                <button role="menuitem" class="block w-full px-3 py-2 text-left text-ink-100 hover:bg-ink-800" @click="closeMenu(); openDialog('move', [entry], entry.name)">Move</button>
                <button role="menuitem" class="block w-full px-3 py-2 text-left text-bad hover:bg-ink-800" @click="closeMenu(); openDialog('delete', [entry])">Delete</button>
              </div>
            </div>
          </div>

          <p v-if="!loading && !error && visible.length === 0" class="py-12 text-center text-sm text-ink-400">{{ query ? "No matches." : "This folder is empty." }}</p>
        </div>
      </div>

      <div class="flex items-center justify-between pt-1 text-sm text-ink-400">
        <span>{{ loading ? "Loading…" : query ? `${visible.length} matches` : `${entries.length} of ${total} entries` }}</span>
        <button v-if="next >= 0" class="rounded-lg border border-ink-700 px-4 py-2 text-ink-200 hover:bg-ink-800 disabled:opacity-50" :disabled="loading" @click="load(path, next)">Load more</button>
      </div>
    </div>

    <div v-if="!editor && !blocked && (selectedEntries.length > 0 || progress)" class="fixed bottom-6 left-1/2 z-20 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-ink-700 bg-ink-900 px-4 py-3 text-sm shadow-2xl">
      <span v-if="progress" class="text-ink-300">{{ progress }}</span>
      <template v-else>
        <span class="text-ink-300">{{ selectedEntries.length }} selected</span>
        <button class="rounded-lg bg-accent-500 px-3 py-1.5 font-semibold text-ink-950 disabled:opacity-50" :disabled="busy" @click="download(selectedEntries)">{{ downloadLabel }}</button>
        <button class="rounded-lg border border-ink-700 px-3 py-1.5 text-ink-200 hover:bg-ink-800 disabled:opacity-50" :disabled="busy" @click="openDialog('moveMany', selectedEntries)">Move</button>
        <button class="rounded-lg border border-ink-700 px-3 py-1.5 text-bad hover:bg-ink-800 disabled:opacity-50" :disabled="busy" @click="openDialog('delete', selectedEntries)">Delete</button>
        <button class="px-2 py-1.5 text-ink-400 hover:text-ink-100" @click="selected = []">Clear</button>
      </template>
    </div>
    <Teleport to="body">
      <div v-if="dialog && dialogText" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" @mousedown.self="closeDialog">
        <form role="dialog" aria-modal="true" :aria-label="dialogText.title" class="w-full max-w-lg rounded-2xl border border-ink-700 bg-ink-900 p-6 shadow-2xl" @submit.prevent="submitDialog" @keydown.esc="closeDialog">
          <div class="flex items-start justify-between gap-4">
            <h3 class="text-xl font-semibold text-ink-100">{{ dialogText.title }}</h3>
            <button type="button" class="flex h-8 w-8 items-center justify-center rounded-md text-ink-400 hover:bg-ink-800 hover:text-ink-100" aria-label="Close" @click="closeDialog">
              <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
            </button>
          </div>
          <div v-if="dialog.kind === 'delete'" class="mt-4 text-sm text-ink-300">
            <p>{{ deleteText }}</p>
            <ul class="mt-3 max-h-40 space-y-1 overflow-auto rounded-lg bg-ink-800 p-3 font-mono text-xs text-ink-100">
              <li v-for="item in dialog.entries" :key="item.name" class="truncate">{{ item.dir ? item.name + "/" : item.name }}</li>
            </ul>
          </div>
          <label v-else class="mt-5 block text-sm text-ink-300">
            {{ dialogText.label }}
            <input ref="dialogInput" v-model="dialog.value" type="text" autocomplete="off" spellcheck="false" class="mt-2 w-full rounded-lg border border-transparent bg-ink-800 px-3 py-2.5 text-sm text-ink-100 focus:border-accent-500 focus:outline-none" />
          </label>
          <p class="mt-3 text-sm font-semibold text-ink-100">{{ dialogText.hint }}</p>
          <p v-if="dialogPreview" class="mt-2 text-sm text-ink-300">
            <span class="font-semibold text-ink-100">{{ dialog.kind === "moveMany" ? "Destination:" : "New location:" }}</span>
            <code class="ml-2 rounded bg-ink-800 px-1.5 py-0.5 font-mono text-xs text-ink-100">{{ dialogPreview }}</code>
          </p>
          <p v-if="dialogError" class="mt-3 text-sm text-bad">{{ dialogError }}</p>
          <div class="mt-6 flex justify-end">
            <button type="submit" ref="dialogSubmit" class="rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-50" :class="dialog.kind === 'delete' ? 'bg-bad text-white' : 'bg-accent-500 text-ink-950'" :disabled="busy">{{ dialogText.submit }}</button>
          </div>
        </form>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 13px;
  line-height: 18px;
  tab-size: 2;
}
.code-layer {
  display: block;
  width: max-content;
  min-width: 100%;
}
.code-input--overlay {
  color: transparent;
  caret-color: #e5e7eb;
}
.code-input--overlay::selection {
  background: rgba(245, 158, 11, 0.28);
}
.code-surface {
  background: #1e1e20;
}
.code-gutter {
  background: #1a1a1c;
  color: #6e7681;
}
.code-layer {
  color: #aab2bd;
}
.code-layer :deep(.hl-comment),
.code-layer :deep(.hl-punct) {
  color: #6e7681;
}
.code-layer :deep(.hl-key) {
  color: #e6edf3;
}
.code-layer :deep(.hl-value) {
  color: #aab2bd;
}
.code-layer :deep(.hl-string) {
  color: #c9d1d9;
}
.code-layer :deep(.hl-number) {
  color: #f0b35a;
}
.code-layer :deep(.hl-section) {
  color: #f59e0b;
}
</style>
