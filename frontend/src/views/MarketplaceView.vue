<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

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
  tags: string[];
  game: string | null;
  loaders: string[];
  game_versions: string[];
  downloads: number | null;
  updated_at: string | null;
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
  latest_version: string | null;
}

interface Facet {
  value: string;
  count: number;
}

interface Catalog {
  registries: string[];
  total: number;
  tag_options: Facet[];
  author_options: Facet[];
  game_options: Facet[];
  loader_options: Facet[];
  version_options: Facet[];
  category_options: Facet[];
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

interface Kind {
  label: string;
  icon: string;
  tone: string;
}

const ICONS: Record<string, string[]> = {
  game: [
    "M6 12h4m-2-2v4",
    "M15 11h.01",
    "M18 13h.01",
    "M17.32 5H6.68a4 4 0 0 0-3.98 3.59C2.6 9.42 2 14.46 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.41-1.41A2 2 0 0 1 9.83 16h4.34a2 2 0 0 1 1.42.59L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.54-.6-6.58-.68-7.26A4 4 0 0 0 17.32 5z",
  ],
  bot: [
    "M12 8V4H8",
    "M6 8h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2z",
    "M2 14h2",
    "M20 14h2",
    "M15 13v2",
    "M9 13v2",
  ],
  plugin: [
    "M16.5 9.4 7.5 4.21",
    "M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z",
    "M3.27 6.96 12 12.01l8.73-5.05",
    "M12 22.08V12",
  ],
  app: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M14 14h7v7h-7z", "M3 14h7v7H3z"],
  box: ["M21 8 12 3 3 8v8l9 5 9-5z", "m3 8 9 5 9-5", "M12 13v8"],
  search: ["m21 21-4.3-4.3", "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z"],
  check: ["M20 6 9 17l-5-5"],
  shield: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"],
  refresh: ["M3 12a9 9 0 0 1 15-6.7L21 8", "M21 3v5h-5", "M21 12a9 9 0 0 1-15 6.7L3 16", "M3 21v-5h5"],
  download: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "m7 10 5 5 5-5", "M12 15V3"],
  clock: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 6v6l4 2"],
  down: ["M12 5v14", "m19 12-7 7-7-7"],
  up: ["M12 19V5", "m5 12 7-7 7 7"],
  x: ["M18 6 6 18", "m6 6 12 12"],
  grid: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M14 14h7v7h-7z", "M3 14h7v7H3z"],
  list: ["M8 6h13", "M8 12h13", "M8 18h13", "M3 6h.01", "M3 12h.01", "M3 18h.01"],
  lock: ["M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z", "M7 11V7a5 5 0 0 1 10 0v4"],
  mod: [
    "M19.44 7.85c-.05.32.06.65.29.88l1.57 1.57a2.4 2.4 0 0 1 0 3.4l-1.61 1.62a.98.98 0 0 1-.84.27c-.47-.07-.8-.48-.97-.92a2.5 2.5 0 1 0-3.21 3.21c.44.17.85.5.92.97a.98.98 0 0 1-.27.84l-1.61 1.61a2.4 2.4 0 0 1-3.41 0l-1.57-1.57a1.03 1.03 0 0 0-.88-.29c-.49.07-.84.5-1.02.97a2.5 2.5 0 1 1-3.24-3.24c.47-.18.9-.53.97-1.02a1.03 1.03 0 0 0-.29-.88l-1.57-1.57a2.4 2.4 0 0 1 0-3.4l1.53-1.53c.24-.24.58-.35.92-.3.51.08.88.53 1.07 1.01a2.5 2.5 0 1 0 3.26-3.26c-.48-.19-.93-.56-1.01-1.07-.05-.34.06-.68.3-.92l1.53-1.53a2.4 2.4 0 0 1 3.4 0l1.57 1.57c.23.23.56.34.88.29.49-.07.84-.5 1.02-.97a2.5 2.5 0 1 1 3.24 3.24c-.47.18-.9.53-.97 1.02z",
  ],
  modpack: [
    "M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z",
    "m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65",
    "m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65",
  ],
  web: [
    "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z",
    "M2 12h20",
    "M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z",
  ],
  database: [
    "M12 8c4.97 0 9-1.34 9-3s-4.03-3-9-3-9 1.34-9 3 4.03 3 9 3z",
    "M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5",
    "M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3",
  ],
  voice: ["M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z", "M19 10v2a7 7 0 0 1-14 0v-2", "M12 19v3"],
};

const KINDS: Record<string, Kind> = {
  game: { label: "Game", icon: "game", tone: "kind-game" },
  plugin: { label: "Plugin", icon: "plugin", tone: "kind-plugin" },
  mod: { label: "Mod", icon: "mod", tone: "kind-mod" },
  modpack: { label: "Modpack", icon: "modpack", tone: "kind-modpack" },
  bot: { label: "Bot", icon: "bot", tone: "kind-bot" },
  app: { label: "App", icon: "web", tone: "kind-app" },
  database: { label: "Database", icon: "database", tone: "kind-database" },
  voice: { label: "Voice", icon: "voice", tone: "kind-voice" },
  // Older names, still stored for packages installed before the split.
  egg: { label: "Game", icon: "game", tone: "kind-game" },
  "bot-template": { label: "Bot", icon: "bot", tone: "kind-bot" },
  "docker-template": { label: "App", icon: "web", tone: "kind-app" },
};

const TYPES = [
  { value: "", label: "All", icon: "box", tone: "kind-box" },
  { value: "game", label: "Games", icon: "game", tone: "kind-game" },
  { value: "plugin", label: "Plugins", icon: "plugin", tone: "kind-plugin" },
  { value: "mod", label: "Mods", icon: "mod", tone: "kind-mod" },
  { value: "modpack", label: "Modpacks", icon: "modpack", tone: "kind-modpack" },
  { value: "bot", label: "Bots", icon: "bot", tone: "kind-bot" },
  { value: "app", label: "Apps & Web", icon: "web", tone: "kind-app" },
  { value: "database", label: "Databases", icon: "database", tone: "kind-database" },
  { value: "voice", label: "Voice", icon: "voice", tone: "kind-voice" },
];

const TYPE_GROUPS = [
  { label: "", values: ["", "game", "bot", "app", "database", "voice"] },
].map((group) => ({ label: group.label, items: TYPES.filter((t) => group.values.includes(t.value)) }));

const GAMES: Record<string, string> = {
  "7dtd": "7 Days to Die",
  ark: "ARK",
  cs2: "Counter-Strike 2",
  gmod: "Garry's Mod",
  minecraft: "Minecraft",
  palworld: "Palworld",
  rust: "Rust",
  satisfactory: "Satisfactory",
  scpsl: "SCP: Secret Laboratory",
  terraria: "Terraria",
  unturned: "Unturned",
  valheim: "Valheim",
  enshrouded: "Enshrouded",
  factorio: "Factorio",
  "project-zomboid": "Project Zomboid",
  "space-engineers": "Space Engineers",
  tf2: "Team Fortress 2",
  "v-rising": "V Rising",
};

const LOADERS: Record<string, string> = {
  paper: "Paper",
  spigot: "Spigot",
  bukkit: "Bukkit",
  purpur: "Purpur",
  folia: "Folia",
  fabric: "Fabric",
  forge: "Forge",
  neoforge: "NeoForge",
  quilt: "Quilt",
  velocity: "Velocity",
  bungeecord: "BungeeCord",
  waterfall: "Waterfall",
  oxide: "Oxide",
  carbon: "Carbon",
  exiled: "EXILED",
  labapi: "LabAPI",
  rocketmod: "RocketMod",
  openmod: "OpenMod",
  bepinex: "BepInEx",
  tmodloader: "tModLoader",
  counterstrikesharp: "CounterStrikeSharp",
  metamod: "Metamod",
  sourcemod: "SourceMod",
};

function pretty(map: Record<string, string>, value: string): string {
  return map[value] ?? value.charAt(0).toUpperCase() + value.slice(1);
}

const SORTS = [
  { value: "newest", label: "Newest" },
  { value: "popular", label: "Most downloaded" },
  { value: "name", label: "Name" },
];

const VIEW_KEY = "epicwing.marketplace.view";

const SUBMIT_MAIL = "support@epicwing.de";
const SUBMIT_BODY = [
  "Template name:",
  "Type (Game / Bot / Plugin / App):",
  "Short description (1-2 sentences):",
  "Version:",
  "License:",
  "Source repository (link, if any):",
  "Docker image:",
  "Your name and GitHub or Discord (optional):",
  "",
  "Please attach:",
  "- the egg export (.json)",
  "- an icon, PNG 256x256 (optional)",
  "",
  "[ ] I made this template or have the right to publish it.",
  "[ ] The install script only does what is needed to set up the server.",
].join("\n");
const SUBMIT_URL =
  "mailto:" + SUBMIT_MAIL +
  "?subject=" + encodeURIComponent("Marketplace submission: ") +
  "&body=" + encodeURIComponent(SUBMIT_BODY);

function kind(value: string): Kind {
  return KINDS[value] ?? { label: value, icon: "box", tone: "kind-box" };
}

function count(value: number): string {
  if (value >= 1000000) return (value / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
  if (value >= 1000) return (value / 1000).toFixed(1).replace(/\.0$/, "") + "K";
  return String(value);
}

function ago(value: string | null): string {
  if (!value) return "";
  const then = new Date(value + "T00:00:00").getTime();
  if (Number.isNaN(then)) return "";
  const days = Math.floor((Date.now() - then) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return days + " days ago";
  const months = Math.floor(days / 30);
  if (months < 12) return months === 1 ? "1 month ago" : months + " months ago";
  const years = Math.floor(days / 365);
  return years === 1 ? "1 year ago" : years + " years ago";
}

function day(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString();
}

function letter(name: string): string {
  return name.trim().charAt(0).toUpperCase() || "?";
}

function readView(): "grid" | "list" {
  try {
    return localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

const tab = ref<"discover" | "installed">("discover");
const view = ref<"grid" | "list">(readView());
const items = ref<PackageItem[]>([]);
const installed = ref<InstalledItem[]>([]);
const registries = ref<string[]>([]);
const errors = ref<string[]>([]);
const tagOptions = ref<Facet[]>([]);
const authorOptions = ref<Facet[]>([]);
const gameOptions = ref<Facet[]>([]);
const loaderOptions = ref<Facet[]>([]);
const versionOptions = ref<Facet[]>([]);
const categoryOptions = ref<Facet[]>([]);
const total = ref(0);
const firstLoad = ref(true);
const loading = ref(false);
const loadingMore = ref(false);
const busy = ref(false);
const error = ref("");
const notice = ref("");

const search = ref("");
const searchBox = ref<HTMLInputElement | null>(null);
const category = ref("");
const sort = ref("newest");
const order = ref("");
const selectedTags = ref<string[]>([]);
const author = ref("");
const game = ref("");
const loader = ref("");
const gameVersion = ref("");
const perPage = ref(24);
const showAllTags = ref(false);
const showAllAuthors = ref(false);

const target = ref<PackageItem | null>(null);
const details = ref<Preview | null>(null);
const detailsLoading = ref(false);
const detailsError = ref("");
const modalTab = ref<"overview" | "variables" | "script">("overview");

const descending = computed(() => (order.value ? order.value === "desc" : sort.value !== "name"));
const tagChoices = computed(() => {
  const known = new Set(tagOptions.value.map((t) => t.value));
  const extra = selectedTags.value.filter((t) => !known.has(t)).map((value) => ({ value, count: 0 }));
  return [...tagOptions.value, ...extra];
});
const authorChoices = computed(() => {
  const known = authorOptions.value.some((a) => a.value === author.value);
  return author.value && !known ? [...authorOptions.value, { value: author.value, count: 0 }] : authorOptions.value;
});
const visibleTags = computed(() => (showAllTags.value ? tagChoices.value : tagChoices.value.slice(0, 12)));
const visibleAuthors = computed(() => (showAllAuthors.value ? authorChoices.value : authorChoices.value.slice(0, 6)));

function typeCount(value: string): number {
  if (!value) return categoryOptions.value.reduce((sum, f) => sum + f.count, 0);
  return categoryOptions.value.find((f) => f.value === value)?.count ?? 0;
}

const activeFilters = computed(() => {
  const list: { key: string; label: string; clear: () => void }[] = [];
  const q = search.value.trim();
  if (q) list.push({ key: "q", label: "“" + q + "”", clear: () => (search.value = "") });
  if (category.value) {
    const label = TYPES.find((t) => t.value === category.value)?.label ?? category.value;
    list.push({ key: "type", label, clear: () => (category.value = "") });
  }
  if (author.value) list.push({ key: "author", label: "by " + author.value, clear: () => (author.value = "") });
  if (game.value) list.push({ key: "game", label: pretty(GAMES, game.value), clear: () => (game.value = "") });
  if (loader.value) list.push({ key: "loader", label: pretty(LOADERS, loader.value), clear: () => (loader.value = "") });
  if (gameVersion.value) list.push({ key: "version", label: gameVersion.value, clear: () => (gameVersion.value = "") });
  for (const tag of selectedTags.value) list.push({ key: "tag:" + tag, label: "#" + tag, clear: () => toggleTag(tag) });
  return list;
});

let requestId = 0;
let timer: ReturnType<typeof setTimeout> | undefined;

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : "The server could not be reached.";
}

async function load(reset = true, refresh = false): Promise<void> {
  const id = ++requestId;
  if (reset) loading.value = true;
  else loadingMore.value = true;
  const params = new URLSearchParams({
    limit: String(perPage.value),
    offset: String(reset ? 0 : items.value.length),
    sort: sort.value,
  });
  if (order.value) params.set("order", order.value);
  if (search.value.trim()) params.set("q", search.value.trim());
  if (category.value) params.set("category", category.value);
  if (author.value) params.set("author", author.value);
  if (game.value) params.set("game", game.value);
  if (loader.value) params.set("loader", loader.value);
  if (gameVersion.value) params.set("version", gameVersion.value);
  for (const tag of selectedTags.value) params.append("tag", tag);
  if (refresh) params.set("refresh", "true");
  try {
    const data = await api<Catalog>("/marketplace?" + params.toString());
    if (id !== requestId) return;
    items.value = reset ? data.packages : [...items.value, ...data.packages];
    installed.value = data.installed;
    registries.value = data.registries;
    errors.value = data.errors;
    tagOptions.value = data.tag_options;
    authorOptions.value = data.author_options;
    gameOptions.value = data.game_options;
    loaderOptions.value = data.loader_options;
    versionOptions.value = data.version_options;
    categoryOptions.value = data.category_options;
    total.value = data.total;
    error.value = "";
  } catch (cause) {
    if (id === requestId) error.value = message(cause);
  } finally {
    if (id === requestId) {
      loading.value = false;
      loadingMore.value = false;
      firstLoad.value = false;
    }
  }
}

function toggleTag(tag: string): void {
  selectedTags.value = selectedTags.value.includes(tag)
    ? selectedTags.value.filter((t) => t !== tag)
    : [...selectedTags.value, tag];
}

function flip(): void {
  order.value = descending.value ? "asc" : "desc";
}

function clearAll(): void {
  search.value = "";
  category.value = "";
  author.value = "";
  game.value = "";
  loader.value = "";
  gameVersion.value = "";
  selectedTags.value = [];
}

async function loadDetails(pkg: PackageItem): Promise<void> {
  detailsLoading.value = true;
  detailsError.value = "";
  try {
    const data = await api<Preview>("/marketplace/preview", {
      method: "POST",
      body: { registry: pkg.registry, package_id: pkg.id },
    });
    if (target.value === pkg) details.value = data;
  } catch (cause) {
    if (target.value === pkg) detailsError.value = message(cause);
  } finally {
    detailsLoading.value = false;
  }
}

function open(pkg: PackageItem): void {
  target.value = pkg;
  details.value = null;
  detailsError.value = "";
  modalTab.value = "overview";
  error.value = "";
  notice.value = "";
  void loadDetails(pkg);
}

function close(): void {
  if (busy.value) return;
  target.value = null;
  details.value = null;
  detailsError.value = "";
}

async function install(): Promise<void> {
  const pkg = target.value;
  if (!pkg || busy.value) return;
  busy.value = true;
  detailsError.value = "";
  try {
    await api("/marketplace/install", {
      method: "POST",
      body: { registry: pkg.registry, package_id: pkg.id },
    });
    busy.value = false;
    notice.value = pkg.name + " was installed. You find it under Nests & Eggs.";
    close();
    await load(true);
  } catch (cause) {
    detailsError.value = message(cause);
  } finally {
    busy.value = false;
  }
}

async function update(item: InstalledItem): Promise<void> {
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await api(`/marketplace/installed/${item.id}/update`, { method: "POST" });
    notice.value = `${item.name} was updated to v${item.latest_version}. New servers and reinstalls use the new version.`;
    await load(true);
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

async function remove(item: InstalledItem): Promise<void> {
  if (!window.confirm("Remove " + item.name + "? Its template is deleted, including your changes to it.")) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    await api("/marketplace/installed/" + item.id, { method: "DELETE" });
    notice.value = item.name + " was removed.";
    await load(true);
  } catch (cause) {
    error.value = message(cause);
  } finally {
    busy.value = false;
  }
}

function onKey(event: KeyboardEvent): void {
  if (event.key === "Escape" && target.value) {
    close();
    return;
  }
  const el = event.target as HTMLElement | null;
  const typing = !!el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable);
  if (event.key === "/" && !typing && !target.value && tab.value === "discover") {
    event.preventDefault();
    searchBox.value?.focus();
  }
}

watch(view, (value) => {
  try {
    localStorage.setItem(VIEW_KEY, value);
  } catch {
    // Storage is blocked, the choice then lasts for this visit only.
  }
});
watch(search, () => {
  clearTimeout(timer);
  timer = setTimeout(() => void load(true), 300);
});
watch(sort, () => {
  order.value = "";
});
watch([sort, order, category, author, game, loader, gameVersion, perPage, selectedTags], () => void load(true));
onMounted(() => {
  void load(true);
  document.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  clearTimeout(timer);
  document.removeEventListener("keydown", onKey);
});
</script>

<template>
  <AppLayout title="Marketplace" subtitle="Templates for your servers." area="admin">
    <div class="space-y-6">
      <p v-if="error" class="rounded-lg border border-bad/30 bg-bad/10 px-4 py-2.5 text-sm text-bad">{{ error }}</p>
      <p v-if="notice" class="rounded-lg border border-ok/30 bg-ok/10 px-4 py-2.5 text-sm text-ok">{{ notice }}</p>
      <p v-for="item in errors" :key="item" class="rounded-lg border border-ink-700 bg-ink-900 px-4 py-2.5 text-xs text-ink-400">{{ item }}</p>

      <div v-if="firstLoad" class="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <div class="hidden space-y-3 lg:block">
          <div v-for="n in 5" :key="n" class="skeleton h-8" />
        </div>
        <div class="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
          <div v-for="n in 6" :key="n" class="skeleton h-56 !rounded-xl" />
        </div>
      </div>

      <div v-else-if="registries.length === 0" class="rounded-xl border border-ink-700 bg-ink-900 p-10 text-center">
        <div class="kind-tile kind-box mx-auto flex h-14 w-14 items-center justify-center rounded-xl">
          <svg viewBox="0 0 24 24" class="h-7 w-7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path v-for="d in ICONS.box" :key="d" :d="d" />
          </svg>
        </div>
        <p class="mt-4 text-base font-semibold text-ink-100">No catalog yet</p>
        <p class="mx-auto mt-2 max-w-md text-sm text-ink-400">
          Allow a catalog in the panel settings with
          <span class="font-mono text-accent-300">EPICWING_MARKETPLACE_REGISTRIES=owner/repository</span>
          and restart the panel.
        </p>
      </div>

      <template v-else>
        <nav class="flex gap-6 border-b border-ink-700">
          <button
            class="-mb-px border-b-2 pb-3 text-sm font-medium transition"
            :class="tab === 'discover' ? 'border-accent-500 text-ink-100' : 'border-transparent text-ink-400 hover:text-ink-200'"
            @click="tab = 'discover'"
          >
            Discover
          </button>
          <button
            class="-mb-px flex items-center gap-2 border-b-2 pb-3 text-sm font-medium transition"
            :class="tab === 'installed' ? 'border-accent-500 text-ink-100' : 'border-transparent text-ink-400 hover:text-ink-200'"
            @click="tab = 'installed'"
          >
            Installed
            <span class="rounded-full bg-ink-800 px-2 py-0.5 text-xs text-ink-300">{{ installed.length }}</span>
          </button>
        </nav>

        <div v-if="tab === 'discover'" class="tab-in grid gap-8 lg:grid-cols-[15rem_minmax(0,1fr)]">
          <aside class="space-y-7 lg:sticky lg:top-6 lg:self-start">
            <section class="space-y-5">
              <div v-for="group in TYPE_GROUPS" :key="group.label || 'all'">
                <h3 v-if="group.label" class="mb-1.5 px-1 text-[11px] font-medium uppercase tracking-wider text-ink-500">
                  {{ group.label }}
                </h3>
                <div class="flex gap-1 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
                  <button
                    v-for="item in group.items"
                    :key="item.value"
                    class="flex shrink-0 items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition"
                    :class="
                      category === item.value
                        ? 'bg-ink-800 text-ink-100'
                        : typeCount(item.value)
                          ? 'text-ink-300 hover:bg-ink-900 hover:text-ink-100'
                          : 'text-ink-500 hover:bg-ink-900 hover:text-ink-300'
                    "
                    @click="category = item.value"
                  >
                    <span
                      class="kind-tile flex h-7 w-7 shrink-0 items-center justify-center rounded-md"
                      :class="[item.tone, { 'opacity-40': !typeCount(item.value) && category !== item.value }]"
                    >
                      <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path v-for="d in ICONS[item.icon]" :key="d" :d="d" />
                      </svg>
                    </span>
                    <span class="flex-1 text-left">{{ item.label }}</span>
                    <span class="pl-2 text-xs tabular-nums text-ink-500">{{ typeCount(item.value) }}</span>
                  </button>
                </div>
              </div>
            </section>

            <section v-if="tagChoices.length">
              <div class="mb-2 flex items-center justify-between px-1">
                <h3 class="text-[11px] font-medium uppercase tracking-wider text-ink-500">Tags</h3>
                <button v-if="selectedTags.length" class="text-xs text-accent-400 hover:text-accent-300" @click="selectedTags = []">Reset</button>
              </div>
              <p v-if="!tagChoices.length" class="px-1 text-xs text-ink-500">No tags yet</p>
              <div class="flex flex-wrap gap-1.5">
                <button
                  v-for="item in visibleTags"
                  :key="item.value"
                  class="rounded-full border px-2.5 py-1 text-xs transition"
                  :class="
                    selectedTags.includes(item.value)
                      ? 'border-accent-500/60 bg-accent-500/10 text-accent-400'
                      : 'border-ink-700 text-ink-300 hover:border-ink-600 hover:text-ink-100'
                  "
                  @click="toggleTag(item.value)"
                >
                  {{ item.value }}<span class="ml-1.5 text-ink-500">{{ item.count }}</span>
                </button>
              </div>
              <button
                v-if="tagChoices.length > 12"
                class="mt-2 px-1 text-xs text-ink-400 hover:text-ink-100"
                @click="showAllTags = !showAllTags"
              >
                {{ showAllTags ? "Show less" : "Show all " + tagChoices.length }}
              </button>
            </section>

            <section class="rounded-xl border border-ink-700 bg-ink-900 p-4">
              <p class="text-sm font-semibold text-ink-100">Submit a template</p>
              <p class="mt-1 text-xs leading-5 text-ink-400">
                Made a server template? Send it to us. We review every submission before it appears here.
              </p>
              <a
                :href="SUBMIT_URL"
                class="mt-3 flex items-center justify-center rounded-lg border border-ink-700 px-3 py-2 text-sm text-ink-100 transition hover:border-accent-500 hover:text-accent-400"
              >
                Email {{ SUBMIT_MAIL }}
              </a>
            </section>
          </aside>

          <section class="min-w-0 space-y-4">
            <div class="flex flex-wrap gap-2">
              <label class="relative min-w-[16rem] flex-1">
                <svg viewBox="0 0 24 24" class="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-500" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path v-for="d in ICONS.search" :key="d" :d="d" />
                </svg>
                <input
                  ref="searchBox"
                  v-model="search"
                  placeholder="Search templates"
                  class="h-10 w-full rounded-lg border border-ink-700 bg-ink-900 pl-10 pr-12 text-sm text-ink-100 outline-none placeholder:text-ink-500 focus:border-accent-500"
                />
                <button
                  v-if="search"
                  class="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-ink-400 hover:text-ink-100"
                  aria-label="Clear search"
                  @click="search = ''"
                >
                  <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
                    <path v-for="d in ICONS.x" :key="d" :d="d" />
                  </svg>
                </button>
                <kbd
                  v-else
                  class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded border border-ink-700 px-1.5 font-mono text-[11px] text-ink-500"
                >/</kbd>
              </label>

              <div class="flex h-10 items-center rounded-lg border border-ink-700 bg-ink-900">
                <span class="pl-3 text-xs text-ink-500">Sort</span>
                <select v-model="sort" class="h-full bg-transparent pl-2 pr-1 text-sm text-ink-100 outline-none">
                  <option v-for="item in SORTS" :key="item.value" :value="item.value" class="bg-ink-900">{{ item.label }}</option>
                </select>
                <button
                  class="flex h-full items-center border-l border-ink-700 px-2.5 text-ink-400 hover:text-ink-100"
                  :title="descending ? 'Descending' : 'Ascending'"
                  :aria-label="descending ? 'Descending' : 'Ascending'"
                  @click="flip"
                >
                  <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path v-for="d in descending ? ICONS.down : ICONS.up" :key="d" :d="d" />
                  </svg>
                </button>
              </div>

              <div class="flex h-10 rounded-lg border border-ink-700 bg-ink-900 p-1">
                <button
                  v-for="mode in (['grid', 'list'] as const)"
                  :key="mode"
                  class="flex w-8 items-center justify-center rounded-md transition"
                  :class="view === mode ? 'bg-ink-700 text-ink-100' : 'text-ink-500 hover:text-ink-100'"
                  :aria-label="mode === 'grid' ? 'Grid view' : 'List view'"
                  :title="mode === 'grid' ? 'Grid view' : 'List view'"
                  @click="view = mode"
                >
                  <svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path v-for="d in ICONS[mode]" :key="d" :d="d" />
                  </svg>
                </button>
              </div>

              <button
                class="flex h-10 w-10 items-center justify-center rounded-lg border border-ink-700 bg-ink-900 text-ink-400 transition hover:text-ink-100 disabled:opacity-40"
                :disabled="loading"
                title="Reload the catalog"
                aria-label="Reload the catalog"
                @click="load(true, true)"
              >
                <svg viewBox="0 0 24 24" class="h-4 w-4" :class="{ 'animate-spin': loading }" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path v-for="d in ICONS.refresh" :key="d" :d="d" />
                </svg>
              </button>
            </div>

            <div class="flex min-h-7 flex-wrap items-center gap-2 text-sm">
              <span class="mr-1 text-ink-400">
                <span class="font-semibold text-ink-100">{{ total }}</span> {{ total === 1 ? "template" : "templates" }}
              </span>
              <button
                v-for="item in activeFilters"
                :key="item.key"
                class="flex items-center gap-1.5 rounded-full border border-ink-700 bg-ink-900 py-1 pl-3 pr-2 text-xs text-ink-200 transition hover:border-ink-600"
                @click="item.clear()"
              >
                {{ item.label }}
                <svg viewBox="0 0 24 24" class="h-3 w-3 text-ink-500" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true">
                  <path v-for="d in ICONS.x" :key="d" :d="d" />
                </svg>
              </button>
              <button v-if="activeFilters.length > 1" class="text-xs text-accent-400 hover:text-accent-300" @click="clearAll">Clear all</button>
            </div>

            <div
              v-if="!loading && items.length === 0"
              class="rounded-xl border border-dashed border-ink-700 px-6 py-14 text-center"
            >
              <p class="text-ink-100">Nothing found</p>
              <p class="mt-1 text-sm text-ink-400">Try another word or loosen the filters.</p>
              <button v-if="activeFilters.length" class="mt-4 text-sm text-accent-400 hover:text-accent-300" @click="clearAll">Clear all filters</button>
            </div>

            <div v-if="view === 'grid'" class="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3" :class="{ 'opacity-60': loading }">
              <article
                v-for="pkg in items"
                :key="pkg.registry + pkg.id"
                role="button"
                tabindex="0"
                class="group flex cursor-pointer flex-col rounded-xl border border-ink-700 bg-ink-900 p-5 transition hover:border-ink-600 hover:bg-ink-800/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50"
                @click="open(pkg)"
                @keydown.enter.self="open(pkg)"
              >
                <div class="flex items-start gap-4">
                  <div class="kind-tile flex h-14 w-14 shrink-0 items-center justify-center rounded-xl" :class="kind(pkg.category).tone">
                    <svg viewBox="0 0 24 24" class="h-7 w-7" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path v-for="d in ICONS[kind(pkg.category).icon]" :key="d" :d="d" />
                    </svg>
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="flex items-start justify-between gap-2">
                      <h3 class="truncate text-base font-semibold text-ink-100">{{ pkg.name }}</h3>
                    </div>
                    <p class="truncate text-sm text-ink-400">{{ kind(pkg.category).label }}</p>
                  </div>
                </div>

                <p class="mt-4 line-clamp-2 min-h-12 text-sm leading-6 text-ink-400">{{ pkg.description || "No description." }}</p>

                <div v-if="pkg.tags.length" class="mt-3 flex flex-wrap gap-x-3 gap-y-1">
                  <button
                    v-for="tag in pkg.tags.slice(0, 4)"
                    :key="tag"
                    class="text-xs transition"
                    :class="selectedTags.includes(tag) ? 'text-accent-400' : 'text-ink-500 hover:text-ink-200'"
                    @click.stop="toggleTag(tag)"
                  >
                    #{{ tag }}
                  </button>
                </div>

                <div class="mt-5 flex flex-1 items-end justify-between gap-3 border-t border-ink-700 pt-4">
                  <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-400">
                    <span v-if="pkg.downloads" class="flex items-center gap-1.5" :title="pkg.downloads + ' downloads in total'">
                      <svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path v-for="d in ICONS.download" :key="d" :d="d" />
                      </svg>
                      <span class="font-medium text-ink-200">{{ count(pkg.downloads) }}</span>
                    </span>
                    <span v-if="ago(pkg.updated_at)" class="flex items-center gap-1.5" :title="pkg.updated_at ?? ''">
                      <svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                        <path v-for="d in ICONS.clock" :key="d" :d="d" />
                      </svg>
                      {{ ago(pkg.updated_at) }}
                    </span>
                    <span v-if="pkg.game" class="text-ink-300">{{ pretty(GAMES, pkg.game) }}<template v-if="pkg.loaders.length"> · {{ pkg.loaders.slice(0, 2).map((l) => pretty(LOADERS, l)).join(", ") }}</template></span>
                    <span class="font-mono text-ink-500">v{{ pkg.version }}</span>
                  </div>
                  <span v-if="pkg.installed" class="flex shrink-0 items-center gap-1.5 rounded-lg bg-ok/10 px-3 py-1.5 text-xs font-medium text-ok">
                    <svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path v-for="d in ICONS.check" :key="d" :d="d" />
                    </svg>
                    Installed
                  </span>
                  <span v-else-if="!pkg.installable" class="shrink-0 rounded-lg bg-ink-800 px-3 py-1.5 text-xs text-ink-400">Coming soon</span>
                  <button
                    v-else
                    class="shrink-0 rounded-lg bg-accent-500 px-4 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-40"
                    :disabled="busy"
                    @click.stop="open(pkg)"
                  >
                    Install
                  </button>
                </div>
              </article>
            </div>

            <div
              v-else-if="items.length"
              class="divide-y divide-ink-700 overflow-hidden rounded-xl border border-ink-700 bg-ink-900"
              :class="{ 'opacity-60': loading }"
            >
              <article
                v-for="pkg in items"
                :key="pkg.registry + pkg.id"
                role="button"
                tabindex="0"
                class="flex cursor-pointer items-center gap-4 px-5 py-4 transition hover:bg-ink-800/50 focus-visible:bg-ink-800/50 focus-visible:outline-none"
                @click="open(pkg)"
                @keydown.enter.self="open(pkg)"
              >
                <div class="kind-tile flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" :class="kind(pkg.category).tone">
                  <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path v-for="d in ICONS[kind(pkg.category).icon]" :key="d" :d="d" />
                  </svg>
                </div>
                <div class="min-w-0 flex-1">
                  <div class="flex items-baseline gap-2">
                    <h3 class="truncate font-semibold text-ink-100">{{ pkg.name }}</h3>
                    
                  </div>
                  <p class="truncate text-sm text-ink-400">{{ pkg.description || "No description." }}</p>
                </div>
                <div class="hidden shrink-0 items-center gap-5 text-xs text-ink-400 md:flex">
                  <span class="rounded-md bg-ink-800 px-2 py-0.5 text-[11px] font-medium text-ink-300">{{ kind(pkg.category).label }}</span>
                  <span v-if="pkg.downloads" class="flex w-16 items-center gap-1.5">
                    <svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path v-for="d in ICONS.download" :key="d" :d="d" />
                    </svg>
                    {{ count(pkg.downloads) }}
                  </span>
                  <span class="w-24 truncate">{{ ago(pkg.updated_at) }}</span>
                </div>
                <span v-if="pkg.installed" class="w-24 shrink-0 text-right text-xs font-medium text-ok">Installed</span>
                <span v-else-if="!pkg.installable" class="w-24 shrink-0 text-right text-xs text-ink-500">Coming soon</span>
                <div v-else class="flex w-24 shrink-0 justify-end">
                  <button
                    class="rounded-lg bg-accent-500 px-4 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-40"
                    :disabled="busy"
                    @click.stop="open(pkg)"
                  >
                    Install
                  </button>
                </div>
              </article>
            </div>

            <div v-if="items.length" class="flex flex-wrap items-center justify-between gap-3 pt-2 text-xs text-ink-400">
              <span>Showing {{ items.length }} of {{ total }}</span>
              <button
                v-if="items.length < total"
                class="rounded-lg border border-ink-700 bg-ink-900 px-5 py-2 text-sm text-ink-200 transition hover:border-ink-600 hover:text-ink-100 disabled:opacity-40"
                :disabled="loadingMore || loading"
                @click="load(false)"
              >
                {{ loadingMore ? "Loading…" : "Load more" }}
              </button>
              <label class="flex items-center gap-2">
                Per page
                <select v-model.number="perPage" class="rounded-md border border-ink-700 bg-ink-900 px-2 py-1 text-ink-100 outline-none focus:border-accent-500">
                  <option :value="12">12</option>
                  <option :value="24">24</option>
                  <option :value="48">48</option>
                </select>
              </label>
            </div>
          </section>
        </div>

        <section v-else class="tab-in">
          <div v-if="installed.length === 0" class="rounded-xl border border-dashed border-ink-700 px-6 py-14 text-center">
            <p class="text-ink-100">Nothing installed yet</p>
            <p class="mt-1 text-sm text-ink-400">Templates you install show up here.</p>
            <button class="mt-4 text-sm text-accent-400 hover:text-accent-300" @click="tab = 'discover'">Browse templates</button>
          </div>
          <div v-else class="divide-y divide-ink-700 overflow-hidden rounded-xl border border-ink-700 bg-ink-900">
            <article v-for="item in installed" :key="item.id" class="flex items-center gap-4 px-5 py-4">
              <div class="kind-tile flex h-11 w-11 shrink-0 items-center justify-center rounded-xl" :class="kind(item.category).tone">
                <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path v-for="d in ICONS[kind(item.category).icon]" :key="d" :d="d" />
                </svg>
              </div>
              <div class="min-w-0 flex-1">
                <h3 class="truncate font-semibold text-ink-100">{{ item.name }}</h3>
                <p class="mt-0.5 text-xs text-ink-400">
                  {{ kind(item.category).label }} · <span class="font-mono">v{{ item.version }}</span><template v-if="day(item.installed_at)"> · installed {{ day(item.installed_at) }}</template>
                </p>
              </div>
              <button
                v-if="item.latest_version && item.latest_version !== item.version"
                class="shrink-0 rounded-lg bg-accent-500 px-4 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-40"
                :disabled="busy"
                @click="update(item)"
              >
                Update to v{{ item.latest_version }}
              </button>
              <button
                class="shrink-0 rounded-lg border border-ink-700 px-4 py-1.5 text-sm text-ink-300 transition hover:border-bad/50 hover:text-bad disabled:opacity-40"
                :disabled="busy"
                @click="remove(item)"
              >
                Remove
              </button>
            </article>
          </div>
        </section>
      </template>
    </div>

    <Teleport to="body">
      <div v-if="target" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" @mousedown.self="close">
        <div
          role="dialog"
          aria-modal="true"
          :aria-label="target.name"
          class="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-900 shadow-2xl"
        >
          <div class="p-6 pb-0">
            <div class="flex items-start gap-4">
              <div class="kind-tile flex h-16 w-16 shrink-0 items-center justify-center rounded-xl" :class="kind(target.category).tone">
                <svg viewBox="0 0 24 24" class="h-8 w-8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path v-for="d in ICONS[kind(target.category).icon]" :key="d" :d="d" />
                </svg>
              </div>
              <div class="min-w-0 flex-1">
                <h2 class="truncate text-xl font-semibold text-ink-100">{{ target.name }}</h2>
                <p class="mt-0.5 text-sm text-ink-400">by {{ target.author }} · {{ kind(target.category).label }}</p>
              </div>
              <button class="rounded-md p-1 text-ink-400 transition hover:text-ink-100" aria-label="Close" :disabled="busy" @click="close">
                <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
                  <path v-for="d in ICONS.x" :key="d" :d="d" />
                </svg>
              </button>
            </div>

            <dl class="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-ink-700 bg-ink-700 sm:grid-cols-4">
              <div class="bg-ink-900 px-4 py-3">
                <dt class="text-[11px] uppercase tracking-wider text-ink-500">Downloads</dt>
                <dd class="mt-0.5 text-sm font-semibold text-ink-100">{{ target.downloads ? count(target.downloads) : "–" }}</dd>
              </div>
              <div class="bg-ink-900 px-4 py-3">
                <dt class="text-[11px] uppercase tracking-wider text-ink-500">Version</dt>
                <dd class="mt-0.5 truncate font-mono text-sm font-semibold text-ink-100">{{ target.version }}</dd>
              </div>
              <div class="bg-ink-900 px-4 py-3">
                <dt class="text-[11px] uppercase tracking-wider text-ink-500">Updated</dt>
                <dd class="mt-0.5 text-sm font-semibold text-ink-100">{{ ago(target.updated_at) || "–" }}</dd>
              </div>
              <div class="bg-ink-900 px-4 py-3">
                <dt class="text-[11px] uppercase tracking-wider text-ink-500">License</dt>
                <dd class="mt-0.5 truncate text-sm font-semibold text-ink-100">{{ target.license || "–" }}</dd>
              </div>
            </dl>

            <nav class="mt-5 flex gap-6 border-b border-ink-700">
              <button
                v-for="item in ([
                  { value: 'overview', label: 'Overview' },
                  { value: 'variables', label: 'Variables' },
                  { value: 'script', label: 'Install script' },
                ] as const)"
                :key="item.value"
                class="-mb-px flex items-center gap-2 border-b-2 pb-3 text-sm font-medium transition"
                :class="modalTab === item.value ? 'border-accent-500 text-ink-100' : 'border-transparent text-ink-400 hover:text-ink-200'"
                @click="modalTab = item.value"
              >
                {{ item.label }}
                <span v-if="item.value === 'variables' && details" class="rounded-full bg-ink-800 px-2 py-0.5 text-xs text-ink-300">{{ details.variables.length }}</span>
              </button>
            </nav>
          </div>

          <div class="min-h-0 flex-1 overflow-y-auto p-6">
            <div v-if="modalTab === 'overview'" class="space-y-5">
              <p class="text-sm leading-6 text-ink-300">{{ target.description || "No description." }}</p>

              <dl v-if="target.game" class="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
                <div>
                  <dt class="text-[11px] uppercase tracking-wider text-ink-500">Game</dt>
                  <dd class="mt-0.5 text-ink-100">{{ pretty(GAMES, target.game) }}</dd>
                </div>
                <div v-if="target.loaders.length">
                  <dt class="text-[11px] uppercase tracking-wider text-ink-500">Loaders</dt>
                  <dd class="mt-0.5 text-ink-100">{{ target.loaders.map((l) => pretty(LOADERS, l)).join(", ") }}</dd>
                </div>
                <div v-if="target.game_versions.length">
                  <dt class="text-[11px] uppercase tracking-wider text-ink-500">Versions</dt>
                  <dd class="mt-0.5 font-mono text-ink-100">
                    {{ target.game_versions.slice(0, 4).join(", ") }}<template v-if="target.game_versions.length > 4"> +{{ target.game_versions.length - 4 }}</template>
                  </dd>
                </div>
              </dl>

              <div v-if="target.tags.length" class="flex flex-wrap gap-1.5">
                <span v-for="tag in target.tags" :key="tag" class="rounded-full border border-ink-700 px-2.5 py-1 text-xs text-ink-300">{{ tag }}</span>
              </div>

              <div class="flex gap-3 rounded-xl border border-ink-700 bg-ink-950 px-4 py-3">
                <svg viewBox="0 0 24 24" class="mt-0.5 h-4 w-4 shrink-0 text-accent-400" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <path v-for="d in ICONS.shield" :key="d" :d="d" />
                </svg>
                <p class="text-sm text-ink-400">
                  This adds a server template. Templates can run setup scripts on your nodes, so only install
                  packages from catalogs you trust.
                </p>
              </div>

              <div v-if="detailsLoading" class="space-y-2">
                <div class="skeleton h-4 w-1/3" />
                <div class="skeleton h-9" />
                <div class="skeleton h-4 w-1/3" />
                <div class="skeleton h-9" />
              </div>
              <template v-if="details">
                <p v-for="item in details.warnings" :key="item" class="rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">{{ item }}</p>
                <div v-if="details.docker_image">
                  <p class="text-[11px] uppercase tracking-wider text-ink-500">Docker image</p>
                  <pre class="mt-1.5 overflow-x-auto rounded-lg bg-ink-950 px-3 py-2 font-mono text-xs text-ink-200">{{ details.docker_image }}</pre>
                </div>
                <div v-if="details.docker_image">
                  <p class="text-[11px] uppercase tracking-wider text-ink-500">Startup command</p>
                  <pre class="mt-1.5 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-ink-950 px-3 py-2 font-mono text-xs text-ink-200">{{ details.startup || "(image default)" }}</pre>
                </div>
                <p class="text-xs text-ink-500">
                  Source: <span class="font-mono text-ink-400">{{ details.repository }} @ {{ details.commit.slice(0, 7) }}</span>
                </p>
              </template>
            </div>

            <div v-else-if="modalTab === 'variables'">
              <div v-if="detailsLoading" class="space-y-2">
                <div v-for="n in 4" :key="n" class="skeleton h-12" />
              </div>
              <div v-else-if="details" class="divide-y divide-ink-700 overflow-hidden rounded-xl border border-ink-700">
                <div v-for="v in details.variables" :key="v.env_variable" class="flex items-center gap-3 px-4 py-3">
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm text-ink-100">{{ v.name }}</p>
                    <p class="truncate font-mono text-xs text-accent-300">{{ v.env_variable }}</p>
                  </div>
                  <span v-if="v.secret" class="flex shrink-0 items-center gap-1 rounded-md bg-ink-800 px-2 py-0.5 text-[11px] text-ink-300">
                    <svg viewBox="0 0 24 24" class="h-3 w-3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                      <path v-for="d in ICONS.lock" :key="d" :d="d" />
                    </svg>
                    Secret
                  </span>
                  <span v-else class="max-w-[40%] shrink-0 truncate font-mono text-xs text-ink-400" :title="v.default_value">{{ v.default_value || "—" }}</span>
                </div>
                <p v-if="!details.variables.length" class="px-4 py-3 text-sm text-ink-500">No variables.</p>
              </div>
            </div>

            <div v-else>
              <div v-if="detailsLoading" class="skeleton h-64" />
              <pre
                v-else-if="details"
                class="max-h-[50vh] overflow-auto rounded-xl border border-ink-700 bg-ink-950 p-4 font-mono text-xs leading-5 text-ink-200"
              >{{ details.install_script || "(none)" }}</pre>
            </div>

            <p v-if="detailsError" class="mt-4 rounded-lg border border-bad/30 bg-bad/10 px-4 py-2 text-sm text-bad">{{ detailsError }}</p>
          </div>

          <div class="flex items-center justify-between gap-3 border-t border-ink-700 px-6 py-4">
            <p class="truncate font-mono text-xs text-ink-500">pinned @ {{ target.commit.slice(0, 7) }}</p>
            <div class="flex shrink-0 gap-2">
              <button
                class="rounded-lg border border-ink-700 px-5 py-2 text-sm text-ink-300 transition hover:bg-ink-800 disabled:opacity-40"
                :disabled="busy"
                @click="close"
              >
                Cancel
              </button>
              <button
                v-if="target.installed"
                class="flex items-center gap-1.5 rounded-lg bg-ok/10 px-5 py-2 text-sm font-medium text-ok"
                disabled
              >
                Installed
              </button>
              <button
                v-else
                class="rounded-lg bg-accent-500 px-6 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-40"
                :disabled="busy || !target.installable"
                @click="install"
              >
                <span v-if="busy" class="spinner mr-1.5" />{{ busy ? "Installing…" : target.installable ? "Install" : "Coming soon" }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </AppLayout>
</template>
