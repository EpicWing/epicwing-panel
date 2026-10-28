<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";

import { ApiError, api } from "../api/client";
import AppLayout from "../components/AppLayout.vue";

interface NestItem {
  id: string;
  name: string;
  description: string;
  egg_count: number;
}

interface VariableRow {
  name: string;
  env_variable: string;
  default_value: string;
  description: string;
  user_editable: boolean;
  user_viewable: boolean;
  rules: string;
}

interface EggItem {
  id: string;
  nest_id: string;
  nest_name: string;
  name: string;
  description: string;
  docker_image: string;
  startup: string;
  stop_command: string;
  install_script: string;
  variables: VariableRow[];
}

interface EggForm {
  nestId: string;
  name: string;
  description: string;
  dockerImage: string;
  startup: string;
  stopCommand: string;
  installScript: string;
  variables: VariableRow[];
}

const { t } = useI18n();

// Only a hint for the start command, the panel fills the values in later.
const placeholderExample = "{{SERVER_NAME}}";
const builtinPlaceholders = "{{SERVER_MEMORY}}, {{SERVER_IP}}, {{SERVER_PORT}}";

function emptyEggForm(nestId: string): EggForm {
  return {
    nestId,
    name: "",
    description: "",
    dockerImage: "",
    startup: "",
    stopCommand: "",
    installScript: "",
    variables: [],
  };
}

const nests = ref<NestItem[]>([]);
const eggs = ref<EggItem[]>([]);
const loading = ref(true);
const error = ref("");
const notice = ref("");
const busy = ref(false);

const showNestForm = ref(false);
const nestForm = ref({ name: "", description: "" });

const eggFormOpen = ref(false);
const editingId = ref<string | null>(null);
const eggForm = ref<EggForm>(emptyEggForm(""));

const inputClass =
  "w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm outline-none transition focus:border-accent-500";
const buttonClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-ink-600 hover:text-ink-100 disabled:opacity-40";
const primaryClass =
  "rounded-md bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const headerPrimaryClass =
  "rounded-md bg-accent-500 px-3 py-1.5 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";
const dangerClass =
  "rounded-md border border-bad/50 px-3 py-1.5 text-xs text-bad transition hover:bg-bad/10 disabled:opacity-40";

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : t("common.unreachable");
}

function eggsOf(nestId: string): EggItem[] {
  return eggs.value.filter((egg) => egg.nest_id === nestId);
}

async function load() {
  try {
    const [nestList, eggList] = await Promise.all([
      api<NestItem[]>("/nests"),
      api<EggItem[]>("/eggs"),
    ]);
    nests.value = nestList;
    eggs.value = eggList;
  } catch (e) {
    error.value = message(e);
  } finally {
    loading.value = false;
  }
}

function toggleNestForm() {
  error.value = "";
  showNestForm.value = !showNestForm.value;
}

async function createNest() {
  error.value = "";
  notice.value = "";
  busy.value = true;
  try {
    await api<NestItem>("/nests", {
      method: "POST",
      body: { name: nestForm.value.name, description: nestForm.value.description },
    });
    nestForm.value = { name: "", description: "" };
    showNestForm.value = false;
    await load();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function removeNest(nest: NestItem) {
  if (!window.confirm(t("eggs.deleteNestConfirm", { name: nest.name }))) {
    return;
  }
  error.value = "";
  notice.value = "";
  try {
    await api<void>(`/nests/${nest.id}`, { method: "DELETE" });
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

function openEggForm(source?: EggItem, copy = false) {
  error.value = "";
  notice.value = "";
  if (source) {
    eggForm.value = {
      nestId: source.nest_id,
      name: copy ? `${source.name} copy` : source.name,
      description: source.description,
      dockerImage: source.docker_image,
      startup: source.startup,
      stopCommand: source.stop_command,
      installScript: source.install_script,
      variables: source.variables.map((v) => ({
        name: v.name,
        env_variable: v.env_variable,
        default_value: v.default_value,
        description: v.description,
        user_editable: v.user_editable,
        user_viewable: v.user_viewable,
        rules: v.rules,
      })),
    };
    editingId.value = copy ? null : source.id;
  } else {
    eggForm.value = emptyEggForm(nests.value[0]?.id ?? "");
    editingId.value = null;
  }
  eggFormOpen.value = true;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function closeEggForm() {
  eggFormOpen.value = false;
  editingId.value = null;
}

function addVariable() {
  eggForm.value.variables.push({
    name: "",
    env_variable: "",
    default_value: "",
    description: "",
    user_editable: true,
    user_viewable: true,
    rules: "nullable|string",
  });
}

function removeVariable(index: number) {
  eggForm.value.variables.splice(index, 1);
}

async function saveEgg() {
  error.value = "";
  notice.value = "";
  const f = eggForm.value;
  const body = {
    nest_id: f.nestId,
    name: f.name,
    description: f.description,
    docker_image: f.dockerImage,
    startup: f.startup,
    stop_command: f.stopCommand,
    install_script: f.installScript,
    variables: f.variables.map((v) => ({
      name: v.name,
      env_variable: v.env_variable,
      default_value: v.default_value,
      description: v.description,
      user_editable: v.user_editable,
      user_viewable: v.user_viewable,
      rules: v.rules,
    })),
  };
  busy.value = true;
  try {
    if (editingId.value) {
      await api<EggItem>(`/eggs/${editingId.value}`, { method: "PATCH", body });
    } else {
      await api<EggItem>("/eggs", { method: "POST", body });
    }
    closeEggForm();
    notice.value = t("eggs.saved");
    await load();
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function removeEgg(egg: EggItem) {
  if (!window.confirm(t("eggs.deleteConfirm", { name: egg.name }))) {
    return;
  }
  error.value = "";
  notice.value = "";
  try {
    await api<void>(`/eggs/${egg.id}`, { method: "DELETE" });
    await load();
  } catch (e) {
    error.value = message(e);
  }
}

const importOpen = ref(false);
const importNestId = ref("");
const warnings = ref<string[]>([]);

function toggleImport() {
  error.value = "";
  importOpen.value = !importOpen.value;
  importNestId.value = nests.value[0]?.id ?? "";
}

async function importEgg(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || !importNestId.value) {
    return;
  }
  error.value = "";
  notice.value = "";
  warnings.value = [];
  busy.value = true;
  try {
    const egg: unknown = JSON.parse(await file.text());
    const result = await api<EggItem & { warnings: string[] }>("/eggs/import", {
      method: "POST",
      body: { nest_id: importNestId.value, egg },
    });
    warnings.value = result.warnings;
    importOpen.value = false;
    notice.value = t("eggs.imported", { name: result.name });
    await load();
  } catch (e) {
    error.value = e instanceof SyntaxError ? t("eggs.importInvalid") : message(e);
  } finally {
    busy.value = false;
  }
}

async function exportEgg(egg: EggItem) {
  error.value = "";
  try {
    const data = await api<unknown>("/eggs/" + egg.id + "/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "egg-" + egg.name.toLowerCase().replace(/[^a-z0-9]+/g, "-") + ".json";
    link.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    error.value = message(e);
  }
}

onMounted(() => void load());
</script>

<template>
  <AppLayout area="admin" :title="t('eggs.title')" :subtitle="t('eggs.subtitle')">
    <template #actions>
      <div class="flex items-center gap-2">
        <button :class="buttonClass" :disabled="nests.length === 0" @click="toggleImport">
          {{ importOpen ? t("eggs.cancel") : t("eggs.importEgg") }}
        </button>
        <button :class="buttonClass" @click="toggleNestForm">
          {{ showNestForm ? t("eggs.cancel") : t("eggs.newNest") }}
        </button>
        <button :class="headerPrimaryClass" :disabled="nests.length === 0" @click="openEggForm()">
          {{ t("eggs.newEgg") }}
        </button>
      </div>
    </template>

    <p
      v-if="error"
      role="alert"
      class="mb-6 rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad"
    >
      {{ error }}
    </p>
    <p
      v-if="notice"
      class="mb-6 rounded-md border border-ok/40 bg-ok/10 px-3 py-2 text-sm text-ok"
    >
      {{ notice }}
    </p>

    <form
      v-if="importOpen"
      class="mb-6 grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5 sm:grid-cols-2"
      @submit.prevent
    >
      <div>
        <label for="import-nest" class="mb-1.5 block text-sm text-ink-300">{{ t("eggs.nest") }}</label>
        <select id="import-nest" v-model="importNestId" :class="inputClass">
          <option v-for="n in nests" :key="n.id" :value="n.id">{{ n.name }}</option>
        </select>
      </div>
      <div>
        <label for="import-file" class="mb-1.5 block text-sm text-ink-300">
          {{ t("eggs.importFile") }}
        </label>
        <input
          id="import-file"
          type="file"
          accept="application/json,.json"
          :disabled="busy || !importNestId"
          class="sr-only"
          @change="importEgg"
        />
        <label
          for="import-file"
          :class="[inputClass, 'block cursor-pointer text-ink-300', busy || !importNestId ? 'cursor-not-allowed opacity-50' : '']"
        >
          Choose file…
        </label>
      </div>
    </form>
    <div
      v-if="warnings.length > 0"
      class="mb-6 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn"
    >
      <p>{{ t("eggs.importWarnings") }}</p>
      <ul class="mt-1 list-disc pl-5">
        <li v-for="w in warnings" :key="w">{{ w }}</li>
      </ul>
    </div>

    <form
      v-if="showNestForm"
      class="mb-6 grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5 sm:grid-cols-2"
      @submit.prevent="createNest"
    >
      <div>
        <label for="nest-name" class="mb-1.5 block text-sm text-ink-300">
          {{ t("eggs.nestName") }}
        </label>
        <input
          id="nest-name"
          v-model="nestForm.name"
          required
          maxlength="64"
          :class="inputClass"
        />
      </div>
      <div>
        <label for="nest-desc" class="mb-1.5 block text-sm text-ink-300">
          {{ t("eggs.nestDescription") }}
        </label>
        <input
          id="nest-desc"
          v-model="nestForm.description"
          maxlength="255"
          :class="inputClass"
        />
      </div>
      <div class="sm:col-span-2">
        <button type="submit" :disabled="busy" :class="primaryClass">
          {{ t("eggs.createNest") }}
        </button>
      </div>
    </form>

    <form
      v-if="eggFormOpen"
      class="mb-6 grid gap-4 rounded-lg border border-ink-700 bg-ink-900 p-5 sm:grid-cols-2"
      @submit.prevent="saveEgg"
    >
      <h2 class="text-lg font-semibold sm:col-span-2">
        {{ editingId ? t("eggs.formEdit") : t("eggs.formCreate") }}
      </h2>
      <div>
        <label for="egg-nest" class="mb-1.5 block text-sm text-ink-300">{{ t("eggs.nest") }}</label>
        <select id="egg-nest" v-model="eggForm.nestId" required :class="inputClass">
          <option v-for="n in nests" :key="n.id" :value="n.id">{{ n.name }}</option>
        </select>
      </div>
      <div>
        <label for="egg-name" class="mb-1.5 block text-sm text-ink-300">{{ t("eggs.name") }}</label>
        <input id="egg-name" v-model="eggForm.name" required maxlength="64" :class="inputClass" />
      </div>
      <div class="sm:col-span-2">
        <label for="egg-desc" class="mb-1.5 block text-sm text-ink-300">
          {{ t("eggs.description") }}
        </label>
        <input id="egg-desc" v-model="eggForm.description" maxlength="255" :class="inputClass" />
      </div>
      <div class="sm:col-span-2">
        <label for="egg-image" class="mb-1.5 block text-sm text-ink-300">{{ t("eggs.image") }}</label>
        <input
          id="egg-image"
          v-model="eggForm.dockerImage"
          required
          maxlength="255"
          placeholder="nginx:1.27-alpine"
          :class="inputClass"
        />
        <p class="mt-1.5 text-xs text-ink-400">{{ t("eggs.imageHint") }}</p>
      </div>
      <div class="sm:col-span-2">
        <label for="egg-startup" class="mb-1.5 block text-sm text-ink-300">
          {{ t("eggs.startup") }}
        </label>
        <input
          id="egg-startup"
          v-model="eggForm.startup"
          maxlength="2048"
          :placeholder="placeholderExample"
          :class="[inputClass, 'font-mono']"
        />
        <p class="mt-1.5 text-xs text-ink-400">
          {{ t("eggs.startupHint", { example: placeholderExample, builtin: builtinPlaceholders }) }}
        </p>
      </div>
      <div class="sm:col-span-2">
        <label for="egg-stop" class="mb-1.5 block text-sm text-ink-300">
          {{ t("eggs.stopCommand") }}
        </label>
        <input
          id="egg-stop"
          v-model="eggForm.stopCommand"
          maxlength="255"
          :class="[inputClass, 'font-mono']"
        />
        <p class="mt-1.5 text-xs text-ink-400">{{ t("eggs.stopHint") }}</p>
      </div>
      <div class="sm:col-span-2">
        <label for="egg-install" class="mb-1.5 block text-sm text-ink-300">
          {{ t("eggs.installScript") }}
        </label>
        <textarea
          id="egg-install"
          v-model="eggForm.installScript"
          rows="6"
          spellcheck="false"
          :class="[inputClass, 'font-mono']"
        ></textarea>
        <p class="mt-1.5 text-xs text-ink-400">{{ t("eggs.installHint") }}</p>
      </div>

      <div class="sm:col-span-2">
        <div class="mb-2 flex items-center justify-between">
          <div>
            <p class="text-sm text-ink-300">{{ t("eggs.variables") }}</p>
            <p class="text-xs text-ink-400">{{ t("eggs.variablesHint") }}</p>
          </div>
          <button type="button" :class="buttonClass" @click="addVariable">
            {{ t("eggs.addVariable") }}
          </button>
        </div>
        <div class="space-y-3">
          <div
            v-for="(variable, index) in eggForm.variables"
            :key="index"
            class="grid gap-3 rounded-md border border-ink-700 bg-ink-950/40 p-3 sm:grid-cols-2"
          >
            <input
              v-model="variable.name"
              required
              maxlength="64"
              :placeholder="t('eggs.varName')"
              :aria-label="t('eggs.varName')"
              :class="inputClass"
            />
            <input
              v-model="variable.env_variable"
              required
              maxlength="64"
              placeholder="SERVER_NAME"
              :aria-label="t('eggs.varEnv')"
              :class="[inputClass, 'font-mono']"
            />
            <input
              v-model="variable.default_value"
              maxlength="1024"
              :placeholder="t('eggs.varDefault')"
              :aria-label="t('eggs.varDefault')"
              :class="inputClass"
            />
            <input
              v-model="variable.description"
              maxlength="255"
              :placeholder="t('eggs.varDescription')"
              :aria-label="t('eggs.varDescription')"
              :class="inputClass"
            />
            <div class="sm:col-span-2">
              <input
                v-model="variable.rules"
                maxlength="512"
                placeholder="required|integer|between:1,100"
                :aria-label="t('eggs.varRules')"
                :class="[inputClass, 'font-mono']"
              />
              <p class="mt-1.5 text-xs text-ink-400">
                {{ t("eggs.varRulesHint", { example: "required|integer|between:1,100" }) }}
              </p>
            </div>
            <div class="flex items-center justify-between sm:col-span-2">
              <div class="flex flex-wrap gap-4">
                <label class="flex items-center gap-2 text-sm text-ink-300">
                  <input v-model="variable.user_viewable" type="checkbox" />
                  {{ t("eggs.varViewable") }}
                </label>
                <label class="flex items-center gap-2 text-sm text-ink-300">
                  <input v-model="variable.user_editable" type="checkbox" />
                  {{ t("eggs.varEditable") }}
                </label>
              </div>
              <button type="button" :class="dangerClass" @click="removeVariable(index)">
                {{ t("eggs.removeVariable") }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="flex gap-2 sm:col-span-2">
        <button type="submit" :disabled="busy" :class="primaryClass">
          {{ busy ? t("eggs.saving") : t("eggs.save") }}
        </button>
        <button type="button" :disabled="busy" :class="buttonClass" @click="closeEggForm">
          {{ t("eggs.cancel") }}
        </button>
      </div>
    </form>

    <div v-if="loading" class="space-y-3 py-4" aria-busy="true"><div class="skeleton h-12"></div><div class="skeleton h-12"></div><div class="skeleton h-12"></div></div>

    <div
      v-else-if="nests.length === 0"
      class="rounded-lg border border-dashed border-ink-700 px-6 py-14 text-center"
    >
      <p class="font-medium">{{ t("eggs.noNests") }}</p>
      <p class="mx-auto mt-1 max-w-md text-sm text-ink-400">{{ t("eggs.noNestsBody") }}</p>
    </div>

    <div v-else class="space-y-6">
      <section
        v-for="nest in nests"
        :key="nest.id"
        class="overflow-hidden rounded-lg border border-ink-700 bg-ink-900"
      >
        <header
          class="flex flex-wrap items-center justify-between gap-3 border-b border-ink-700 px-4 py-3"
        >
          <div class="min-w-0">
            <h2 class="font-semibold">{{ nest.name }}</h2>
            <p v-if="nest.description" class="text-xs text-ink-400">{{ nest.description }}</p>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-xs text-ink-400">{{ t("eggs.eggCount", { count: nest.egg_count }) }}</span>
            <button
              :class="dangerClass"
              :disabled="busy || nest.egg_count > 0"
              @click="removeNest(nest)"
            >
              {{ t("eggs.deleteNest") }}
            </button>
          </div>
        </header>

        <p v-if="eggsOf(nest.id).length === 0" class="px-4 py-6 text-center text-sm text-ink-400">
          {{ t("eggs.noEggs") }}
        </p>
        <div v-else class="overflow-x-auto">
          <table class="w-full text-left text-sm">
            <thead class="text-xs uppercase tracking-wider text-ink-400">
              <tr>
                <th class="px-4 py-2.5 font-medium">{{ t("eggs.colName") }}</th>
                <th class="px-4 py-2.5 font-medium">{{ t("eggs.colImage") }}</th>
                <th class="px-4 py-2.5 font-medium">{{ t("eggs.colVariables") }}</th>
                <th class="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody class="divide-y divide-ink-700">
              <tr v-for="egg in eggsOf(nest.id)" :key="egg.id" class="hover:bg-ink-800/60">
                <td class="px-4 py-3">
                  <p class="font-medium">{{ egg.name }}</p>
                  <p v-if="egg.description" class="text-xs text-ink-400">{{ egg.description }}</p>
                </td>
                <td class="px-4 py-3 font-mono text-xs text-ink-300">{{ egg.docker_image }}</td>
                <td class="px-4 py-3 font-mono text-xs text-ink-300">{{ egg.variables.length }}</td>
                <td class="px-4 py-3">
                  <div class="flex justify-end gap-2">
                    <button :class="buttonClass" @click="openEggForm(egg)">{{ t("eggs.edit") }}</button>
                    <button :class="buttonClass" @click="openEggForm(egg, true)">
                      {{ t("eggs.duplicate") }}
                    </button>
                    <button :class="buttonClass" @click="exportEgg(egg)">
                      {{ t("eggs.exportEgg") }}
                    </button>
                    <button :class="dangerClass" @click="removeEgg(egg)">{{ t("eggs.delete") }}</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </AppLayout>
</template>
