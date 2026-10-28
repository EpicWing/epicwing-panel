<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";

interface StartupVariable {
  name: string;
  env_variable: string;
  description: string;
  rules: string;
  default_value: string;
  value: string;
  user_editable: boolean;
  user_viewable: boolean;
}

interface StartupData {
  startup: string;
  startup_command: string;
  egg_startup: string;
  image: string;
  egg_image: string;
  variables: StartupVariable[];
}

const props = defineProps<{ serverId: string; status: string }>();
const { t } = useI18n();

const placeholderHint = "{{VARIABLE}}";
const data = ref<StartupData | null>(null);
const startup = ref("");
const image = ref("");
const values = ref<Record<string, string>>({});
const loading = ref(true);
const saving = ref(false);
const saved = ref(false);
const error = ref("");
const fieldErrors = ref<Record<string, string>>({});

const running = computed(() => props.status === "running" || props.status === "starting");

const dirty = computed(() => {
  const current = data.value;
  if (!current) return false;
  return (
    startup.value !== current.startup ||
    image.value !== current.image ||
    current.variables.some((v) => values.value[v.env_variable] !== v.value)
  );
});

// While nothing is changed the server's own rendered command is shown. Once the form is
// edited, only the variables are filled in, other placeholders stay as they are.
const commandPreview = computed(() => {
  const current = data.value;
  if (!current) return "";
  if (!dirty.value) return current.startup_command || "—";
  const text = startup.value.replace(/\{\{\s*([A-Z0-9_]+)\s*\}\}/g, (match, key: string) =>
    key in values.value ? values.value[key] : match,
  );
  return text || "—";
});

function message(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : t("common.unreachable");
}

function choices(variable: StartupVariable): string[] {
  const match = /(?:^|\|)in:([^|]+)/.exec(variable.rules);
  return match ? match[1].split(",") : [];
}

function apply(fresh: StartupData): void {
  data.value = fresh;
  startup.value = fresh.startup;
  image.value = fresh.image;
  values.value = Object.fromEntries(fresh.variables.map((v) => [v.env_variable, v.value]));
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    apply(await api<StartupData>(`/servers/${props.serverId}/startup`));
    error.value = "";
  } catch (cause) {
    error.value = message(cause);
  } finally {
    loading.value = false;
  }
}

function discard(): void {
  if (data.value) apply(data.value);
  fieldErrors.value = {};
  error.value = "";
}

async function save(): Promise<void> {
  const current = data.value;
  if (!current || saving.value || !dirty.value) return;
  saving.value = true;
  saved.value = false;
  error.value = "";
  fieldErrors.value = {};
  const body: Record<string, unknown> = {};
  if (startup.value !== current.startup) body.startup = startup.value;
  if (image.value !== current.image) body.image = image.value;
  const changed = Object.fromEntries(
    current.variables
      .filter((v) => v.user_editable && values.value[v.env_variable] !== v.value)
      .map((v) => [v.env_variable, values.value[v.env_variable]]),
  );
  if (Object.keys(changed).length) body.variables = changed;
  try {
    await api(`/servers/${props.serverId}`, { method: "PATCH", body });
    apply(await api<StartupData>(`/servers/${props.serverId}/startup`));
    saved.value = true;
  } catch (cause) {
    const text = message(cause);
    // The API reports rule violations as "<variable name>: <problem>".
    const hit = data.value?.variables.find((v) => text.startsWith(`${v.name}: `));
    if (hit) fieldErrors.value = { [hit.env_variable]: text.slice(hit.name.length + 2) };
    else error.value = text;
  } finally {
    saving.value = false;
  }
}

watch(dirty, (value) => {
  if (value) saved.value = false;
});

onMounted(load);
</script>

<template>
  <div class="space-y-6">
    <div>
      <h2 class="text-4xl font-bold">Startup Settings</h2>
      <p class="mt-2 text-sm text-ink-400">Configure how your server starts and manage its environment variables.</p>
    </div>

    <div v-if="loading" class="rounded-xl border border-ink-700 bg-ink-900 p-8 text-ink-400">Loading startup settings…</div>
    <div v-else-if="!data" class="rounded-xl border border-bad/30 bg-bad/10 p-8 text-bad">{{ error || "Startup settings could not be loaded." }}</div>

    <template v-else>
      <section class="rounded-xl border border-ink-700 bg-ink-900 p-6">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h3 class="text-lg font-semibold">Startup command</h3>
          <button
            v-if="startup !== data.egg_startup"
            class="text-xs text-ink-400 transition hover:text-accent-300"
            @click="startup = data.egg_startup"
          >
            Reset to egg default
          </button>
        </div>
        <p class="mt-2 text-sm text-ink-400">
          This is the command the server runs. Use {{ placeholderHint }} to insert the value of a variable.
        </p>
        <pre class="mt-4 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-ink-950 p-4 font-mono text-sm text-ink-200">{{ commandPreview }}</pre>
        <label class="mt-5 block text-xs uppercase tracking-wider text-ink-400" for="startup-template">Command template</label>
        <textarea
          id="startup-template"
          v-model="startup"
          rows="3"
          spellcheck="false"
          class="mt-2 w-full rounded-lg border border-ink-700 bg-ink-950 px-4 py-3 font-mono text-sm text-ink-100 outline-none focus:border-accent-500"
        />
      </section>

      <section class="rounded-xl border border-ink-700 bg-ink-900 p-6">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h3 class="text-lg font-semibold">Docker image</h3>
          <button
            v-if="image !== data.egg_image"
            class="text-xs text-ink-400 transition hover:text-accent-300"
            @click="image = data.egg_image"
          >
            Reset to egg default
          </button>
        </div>
        <input
          v-model="image"
          spellcheck="false"
          class="mt-4 w-full rounded-lg border border-ink-700 bg-ink-950 px-4 py-3 font-mono text-sm text-ink-100 outline-none focus:border-accent-500"
        />
      </section>

      <section v-if="data.variables.length">
        <h3 class="mb-3 text-lg font-semibold">Variables</h3>
        <div class="grid gap-4 md:grid-cols-2">
          <div
            v-for="variable in data.variables"
            :key="variable.env_variable"
            class="rounded-xl border bg-ink-900 p-5"
            :class="fieldErrors[variable.env_variable] ? 'border-bad/60' : 'border-ink-700'"
          >
            <div class="flex items-start justify-between gap-3">
              <p class="font-semibold text-ink-100">{{ variable.name }}</p>
              <span v-if="!variable.user_editable" class="rounded bg-ink-800 px-2 py-0.5 text-[10px] uppercase tracking-wider text-ink-400">Locked</span>
            </div>
            <p class="mt-1 font-mono text-xs text-accent-300">{{ variable.env_variable }}</p>
            <p v-if="variable.description" class="mt-2 text-sm text-ink-400">{{ variable.description }}</p>

            <select
              v-if="choices(variable).length"
              v-model="values[variable.env_variable]"
              :disabled="!variable.user_editable"
              class="mt-4 w-full rounded-lg border border-ink-700 bg-ink-950 px-4 py-2.5 text-sm text-ink-100 outline-none focus:border-accent-500 disabled:opacity-50"
            >
              <option v-for="choice in choices(variable)" :key="choice" :value="choice">{{ choice }}</option>
            </select>
            <input
              v-else
              v-model="values[variable.env_variable]"
              :readonly="!variable.user_editable"
              spellcheck="false"
              class="mt-4 w-full rounded-lg border border-ink-700 bg-ink-950 px-4 py-2.5 font-mono text-sm text-ink-100 outline-none focus:border-accent-500 read-only:opacity-50"
            />

            <p v-if="fieldErrors[variable.env_variable]" class="mt-2 text-xs text-bad">{{ fieldErrors[variable.env_variable] }}</p>
            <div class="mt-3 flex items-center justify-between gap-3 text-xs text-ink-500">
              <span class="truncate font-mono">{{ variable.rules }}</span>
              <button
                v-if="variable.user_editable && values[variable.env_variable] !== variable.default_value"
                class="shrink-0 text-ink-400 transition hover:text-accent-300"
                @click="values[variable.env_variable] = variable.default_value"
              >
                Reset
              </button>
            </div>
          </div>
        </div>
      </section>

      <p v-if="error" class="rounded-lg border border-bad/30 bg-bad/10 px-4 py-2 text-sm text-bad">{{ error }}</p>

      <div class="flex flex-wrap items-center gap-3">
        <button
          class="rounded-lg bg-accent-500 px-5 py-2.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:cursor-not-allowed disabled:opacity-40"
          :disabled="!dirty || saving"
          @click="save"
        >
          {{ saving ? "Saving…" : "Save changes" }}
        </button>
        <button
          v-if="dirty"
          class="rounded-lg border border-ink-700 px-5 py-2.5 text-sm text-ink-300 transition hover:bg-ink-800 disabled:opacity-40"
          :disabled="saving"
          @click="discard"
        >
          Discard
        </button>
        <p v-if="saved && !dirty" class="text-sm text-ok">Saved.<span v-if="running"> Restart the server to apply the changes.</span></p>
        <p v-else-if="running" class="text-sm text-ink-400">The server is running. Changes apply on the next start.</p>
      </div>
    </template>
  </div>
</template>
