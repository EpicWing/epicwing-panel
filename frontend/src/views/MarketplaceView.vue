<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

interface PackageItem {
  id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  category: string;
  repository: string;
  license: string;
  registry: string;
  commit: string;
  installable: boolean;
  installed: boolean;
  update_available: boolean;
}

interface InstalledItem {
  id: string;
  package_id: string;
  name: string;
  version: string;
  category: string;
  repository: string;
  commit: string;
  egg_id: string | null;
  installed_at: string;
}

interface Catalog {
  registries: string[];
  packages: PackageItem[];
  installed: InstalledItem[];
  errors: string[];
}

interface Preview {
  name: string;
  description: string;
  version: string;
  author: string;
  license: string;
  category: string;
  repository: string;
  commit: string;
  docker_image: string;
  startup: string;
  stop_command: string;
  install_script: string;
  variables: { env_variable: string; name: string; default_value: string; secret: boolean }[];
  warnings: string[];
}

const catalog = ref<Catalog | null>(null);
const loading = ref(true);
const busy = ref(false);
const error = ref("");
const notice = ref("");
const search = ref("");
const category = ref("all");
const preview = ref<Preview | null>(null);
const previewFor = ref<PackageItem | null>(null);

const categories = computed(() =>
  ["all", ...Array.from(new Set((catalog.value?.packages ?? []).map((p) => p.category)))],
);

const shown = computed(() => {
  const needle = search.value.trim().toLowerCase();
  return (catalog.value?.packages ?? []).filter(
    (p) =>
      (category.value === "all" || p.category === category.value) &&
      (p.name + " " + p.description + " " + p.author).toLowerCase().includes(needle),
  );
});

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "The server could not be reached.";
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    catalog.value = await api<Catalog>("/marketplace");
    error.value = "";
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}

async function openPreview(pkg: PackageItem): Promise<void> {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    preview.value = await api<Preview>("/marketplace/preview", {
      method: "POST",
      body: { registry: pkg.registry, package_id: pkg.id },
    });
    previewFor.value = pkg;
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

function closePreview(): void {
  preview.value = null;
  previewFor.value = null;
}

async function install(): Promise<void> {
  const pkg = previewFor.value;
  if (!pkg || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api("/marketplace/install", {
      method: "POST",
      body: { registry: pkg.registry, package_id: pkg.id },
    });
    notice.value = pkg.name + " was installed. You find it under Nests & Eggs.";
    closePreview();
    await load();
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

async function remove(item: InstalledItem): Promise<void> {
  if (!window.confirm("Remove " + item.name + "? Its egg is deleted, including your changes to it.")) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await api("/marketplace/installed/" + item.id, { method: "DELETE" });
    notice.value = item.name + " was removed.";
    await load();
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <AppLayout title="Marketplace" subtitle="Packages from trusted GitHub catalogs." area="admin">
    <div class="space-y-4">
      <p v-if="error" class="rounded-lg border border-bad/30 bg-bad/10 px-4 py-2 text-sm text-bad">{{ error }}</p>
      <p v-if="notice" class="rounded-lg border border-ink-700 bg-ink-900 px-4 py-2 text-sm text-ok">{{ notice }}</p>
      <p v-for="item in catalog?.errors ?? []" :key="item" class="rounded-lg border border-ink-700 bg-ink-900 px-4 py-2 text-xs text-ink-400">{{ item }}</p>

      <div v-if="loading" class="rounded-xl border border-ink-700 bg-ink-900 p-8 text-ink-400">Loading marketplace…</div>

      <div v-else-if="catalog && catalog.registries.length === 0" class="rounded-xl border border-ink-700 bg-ink-900 p-6 text-sm text-ink-300">
        <p class="font-semibold text-ink-100">No catalog is set up.</p>
        <p class="mt-2 text-ink-400">
          Add the allowed catalogs to the panel settings as
          <span class="font-mono text-accent-300">EPICWING_MARKETPLACE_REGISTRIES=owner/repository</span>
          (comma separated) and restart the panel.
        </p>
      </div>

      <template v-else-if="catalog">
        <div class="flex flex-wrap gap-3">
          <input
            v-model="search"
            placeholder="Search packages"
            class="min-w-64 flex-1 rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-100 outline-none focus:border-accent-500"
          />
          <select
            v-model="category"
            class="rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-100 outline-none focus:border-accent-500"
          >
            <option v-for="item in categories" :key="item" :value="item">{{ item === "all" ? "All categories" : item }}</option>
          </select>
        </div>

        <p v-if="shown.length === 0" class="text-sm text-ink-400">No packages found.</p>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <div v-for="pkg in shown" :key="pkg.id" class="flex flex-col rounded-xl border border-ink-700 bg-ink-900 p-4">
            <div class="flex items-start justify-between gap-3">
              <p class="font-semibold text-ink-100">{{ pkg.name }}</p>
              <span class="rounded bg-ink-800 px-2 py-0.5 text-[10px] uppercase tracking-wider text-ink-400">{{ pkg.category }}</span>
            </div>
            <p class="mt-1 text-xs text-ink-500">v{{ pkg.version }} · {{ pkg.author }} · {{ pkg.license }}</p>
            <p class="mt-2 flex-1 text-sm leading-5 text-ink-400">{{ pkg.description }}</p>
            <p class="mt-3 truncate font-mono text-xs text-accent-300">{{ pkg.repository }}</p>
            <div class="mt-3 flex items-center justify-between gap-3">
              <span v-if="pkg.installed" class="text-xs text-ok">
                Installed<template v-if="pkg.update_available"> · a different version is available</template>
              </span>
              <span v-else-if="!pkg.installable" class="text-xs text-ink-500">Not installable yet</span>
              <span v-else />
              <button
                v-if="pkg.installable && !pkg.installed"
                class="rounded-lg bg-accent-500 px-3 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-40"
                :disabled="busy"
                @click="openPreview(pkg)"
              >
                Review & install
              </button>
            </div>
          </div>
        </div>

        <section v-if="catalog.installed.length">
          <h3 class="mb-3 mt-6 text-base font-semibold">Installed</h3>
          <div class="space-y-2">
            <div
              v-for="item in catalog.installed"
              :key="item.id"
              class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-ink-700 bg-ink-900 px-4 py-3"
            >
              <div>
                <p class="font-semibold text-ink-100">{{ item.name }} <span class="text-xs font-normal text-ink-500">v{{ item.version }}</span></p>
                <p class="font-mono text-xs text-ink-500">{{ item.repository }} @ {{ item.commit.slice(0, 7) }}</p>
              </div>
              <button
                class="rounded-lg border border-ink-700 px-3 py-1.5 text-sm text-ink-300 transition hover:bg-ink-800 disabled:opacity-40"
                :disabled="busy"
                @click="remove(item)"
              >
                Remove
              </button>
            </div>
          </div>
        </section>
      </template>
    </div>

    <div v-if="preview && previewFor" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div class="max-h-[85vh] w-full max-w-3xl space-y-4 overflow-y-auto rounded-xl border border-ink-700 bg-ink-900 p-6">
        <div>
          <h2 class="text-xl font-semibold">{{ preview.name }}</h2>
          <p class="mt-1 text-xs text-ink-500">
            v{{ preview.version }} · {{ preview.author }} · {{ preview.license }} · {{ preview.repository }} @ {{ preview.commit.slice(0, 7) }}
          </p>
          <p class="mt-2 text-sm text-ink-400">
            This creates an egg. Its install script runs inside a container on the node when a server is installed. Read it first.
          </p>
        </div>

        <p v-for="item in preview.warnings" :key="item" class="rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-xs text-ink-400">{{ item }}</p>

        <div>
          <p class="text-xs uppercase tracking-wider text-ink-400">Docker image</p>
          <pre class="mt-1 overflow-x-auto rounded-lg bg-ink-950 px-3 py-2 font-mono text-xs text-ink-200">{{ preview.docker_image }}</pre>
        </div>
        <div>
          <p class="text-xs uppercase tracking-wider text-ink-400">Startup command</p>
          <pre class="mt-1 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-ink-950 px-3 py-2 font-mono text-xs text-ink-200">{{ preview.startup || "(image default)" }}</pre>
        </div>
        <div>
          <p class="text-xs uppercase tracking-wider text-ink-400">Variables</p>
          <div class="mt-1 divide-y divide-ink-800 rounded-lg bg-ink-950 text-xs">
            <div v-for="v in preview.variables" :key="v.env_variable" class="flex items-center justify-between gap-3 px-3 py-2">
              <span class="font-mono text-accent-300">{{ v.env_variable }}</span>
              <span class="truncate text-ink-400">{{ v.name }}</span>
              <span v-if="v.secret" class="rounded bg-ink-800 px-2 py-0.5 text-[10px] uppercase tracking-wider text-ink-400">Secret</span>
            </div>
            <p v-if="!preview.variables.length" class="px-3 py-2 text-ink-500">None</p>
          </div>
        </div>
        <div>
          <p class="text-xs uppercase tracking-wider text-ink-400">Install script</p>
          <pre class="mt-1 max-h-64 overflow-auto rounded-lg bg-ink-950 px-3 py-2 font-mono text-xs text-ink-200">{{ preview.install_script || "(none)" }}</pre>
        </div>

        <div class="flex justify-end gap-2">
          <button
            class="rounded-lg border border-ink-700 px-4 py-2 text-sm text-ink-300 transition hover:bg-ink-800 disabled:opacity-40"
            :disabled="busy"
            @click="closePreview"
          >
            Cancel
          </button>
          <button
            class="rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-40"
            :disabled="busy"
            @click="install"
          >
            {{ busy ? "Installing…" : "Install" }}
          </button>
        </div>
      </div>
    </div>
  </AppLayout>
</template>
