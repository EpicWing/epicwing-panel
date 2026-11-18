<script setup lang="ts">
import { ref } from "vue";

import { ApiError, api, apiUpload } from "../api/client";
import { bumpAvatars } from "../lib/avatar";
import { auth } from "../stores/auth";
import UserAvatar from "./UserAvatar.vue";

const MAX_BYTES = 1024 * 1024;

const error = ref("");
const done = ref("");
const busy = ref(false);
const input = ref<HTMLInputElement | null>(null);
const name = ref(auth.state.user?.display_name ?? "");
const nameBusy = ref(false);
const nameDone = ref("");

const ghostClass =
  "rounded-md border border-ink-700 px-3 py-1.5 text-xs text-ink-300 transition hover:border-accent-500 disabled:opacity-40";
const primaryClass =
  "rounded-lg bg-accent-500 px-4 py-2 text-sm font-semibold text-ink-950 transition hover:bg-accent-400 disabled:opacity-60";

function message(e: unknown): string {
  return e instanceof ApiError ? e.message : "Could not reach the server.";
}

async function onFile(event: Event) {
  const el = event.target as HTMLInputElement;
  const file = el.files?.[0];
  el.value = "";
  if (!file) return;
  error.value = "";
  done.value = "";
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    error.value = "Only PNG, JPEG and WebP images are allowed.";
    return;
  }
  if (file.size > MAX_BYTES) {
    error.value = "The image must not exceed 1 MB.";
    return;
  }
  busy.value = true;
  try {
    await apiUpload("/avatars/me", file);
    bumpAvatars();
    done.value = "Profile picture updated.";
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}

async function saveName() {
  error.value = "";
  nameDone.value = "";
  nameBusy.value = true;
  try {
    const user = await auth.setName(name.value);
    name.value = user.display_name ?? "";
    nameDone.value = user.display_name ? "Name saved." : "Name removed, your email address is shown again.";
  } catch (e) {
    error.value = message(e);
  } finally {
    nameBusy.value = false;
  }
}

async function remove() {
  error.value = "";
  done.value = "";
  busy.value = true;
  try {
    await api<void>("/avatars/me", { method: "DELETE" });
    bumpAvatars();
    done.value = "Profile picture removed.";
  } catch (e) {
    error.value = message(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="space-y-4 rounded-xl border border-ink-700 bg-ink-900 p-6">
    <div>
      <h2 class="text-lg font-semibold">Profile</h2>
      <p class="mt-1 text-sm text-ink-400">{{ auth.state.user?.email }}</p>
    </div>
    <div>
      <label for="profile-name" class="mb-1.5 block text-sm text-ink-300">Name</label>
      <div class="flex gap-2">
        <input
          id="profile-name"
          v-model="name"
          maxlength="48"
          autocomplete="nickname"
          placeholder="Shown instead of your email address"
          class="w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-ink-100"
          @keydown.enter.prevent="saveName"
        />
        <button type="button" :class="primaryClass" :disabled="nameBusy" @click="saveName">Save</button>
      </div>
      <p v-if="nameDone" role="status" class="mt-2 text-sm text-ink-300">{{ nameDone }}</p>
    </div>
    <div class="flex items-center gap-4">
      <UserAvatar :user-id="auth.state.user?.id" :label="auth.state.user?.display_name || auth.state.user?.email || ''" :size="64" />
      <div class="flex flex-wrap gap-2">
        <input ref="input" type="file" accept="image/png,image/jpeg,image/webp" class="hidden" @change="onFile" />
        <button type="button" :class="primaryClass" :disabled="busy" @click="input?.click()">Upload image</button>
        <button type="button" :class="ghostClass" :disabled="busy" @click="remove">Remove</button>
      </div>
    </div>
    <p class="text-xs text-ink-400">PNG, JPEG or WebP, up to 1 MB.</p>
    <p v-if="error" role="alert" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-bad">{{ error }}</p>
    <p v-if="done" role="status" class="text-sm text-ink-300">{{ done }}</p>
  </section>
</template>
