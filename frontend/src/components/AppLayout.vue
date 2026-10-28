<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";

import { auth } from "../stores/auth";
import LogoMark from "./LogoMark.vue";

const props = withDefaults(
  defineProps<{ title: string; subtitle?: string; area?: "user" | "admin" }>(),
  { area: "user" },
);

interface NavItem {
  label: string;
  to: string | null;
}

interface NavSection {
  heading: string;
  items: NavItem[];
}

const { t } = useI18n();
const router = useRouter();

const sections = computed<NavSection[]>(() => {
  if (props.area === "admin") {
    return [
      {
        heading: t("nav.administration"),
        items: [{ label: t("nav.overview"), to: "/admin" }],
      },
      {
        heading: t("nav.management"),
        items: [
          { label: t("nav.nodes"), to: "/admin/nodes" },
          { label: t("nav.allServers"), to: null },
          { label: t("nav.users"), to: null },
        ],
      },
    ];
  }
  return [
    {
      heading: t("nav.account"),
      items: [
        { label: t("nav.servers"), to: "/" },
        { label: t("nav.apiKeys"), to: null },
        { label: t("nav.sshKeys"), to: null },
        { label: t("nav.settings"), to: "/settings" },
      ],
    },
  ];
});

const switchLink = computed<{ label: string; to: string; badge?: string } | null>(() => {
  if (props.area === "admin") {
    return { label: t("nav.backToPanel"), to: "/" };
  }
  if (auth.state.user?.is_admin) {
    return { label: t("nav.adminPanel"), to: "/admin", badge: t("nav.adminBadge") };
  }
  return null;
});

const mobileLinks = computed(() => {
  const links = sections.value
    .flatMap((s) => s.items)
    .filter((i): i is NavItem & { to: string } => !!i.to);
  if (switchLink.value) {
    links.push({ label: switchLink.value.label, to: switchLink.value.to });
  }
  return links;
});

async function logout() {
  try {
    await auth.logout();
  } finally {
    await router.push({ name: "login" });
  }
}
</script>

<template>
  <div class="flex min-h-screen">
    <aside
      class="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-ink-700 bg-ink-900 md:flex"
    >
      <div class="flex items-center gap-2.5 px-5 py-5">
        <LogoMark class="h-6 w-6 text-accent-500" />
        <span class="text-base font-semibold tracking-tight">EpicWing</span>
        <span
          v-if="area === 'admin'"
          class="ml-auto rounded bg-accent-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-400"
        >
          {{ t("nav.adminBadge") }}
        </span>
      </div>

      <nav class="flex-1 overflow-y-auto px-3 pb-4">
        <div v-for="section in sections" :key="section.heading" class="mb-6">
          <p class="px-3 pb-2 text-[11px] font-medium uppercase tracking-wider text-ink-400">
            {{ section.heading }}
          </p>
          <template v-for="item in section.items" :key="item.label">
            <RouterLink
              v-if="item.to"
              :to="item.to"
              class="mb-0.5 block border-l-2 border-transparent px-3 py-1.5 text-sm text-ink-300 transition hover:bg-ink-800 hover:text-ink-100"
              exact-active-class="!border-accent-500 !bg-ink-800 !text-ink-100"
            >
              {{ item.label }}
            </RouterLink>
            <div
              v-else
              class="mb-0.5 flex cursor-not-allowed items-center justify-between border-l-2 border-transparent px-3 py-1.5 text-sm text-ink-600"
            >
              <span>{{ item.label }}</span>
              <span class="text-[10px] uppercase tracking-wide">{{ t("common.soon") }}</span>
            </div>
          </template>
        </div>
      </nav>

      <div class="space-y-3 border-t border-ink-700 p-4">
        <RouterLink
          v-if="switchLink"
          :to="switchLink.to"
          class="flex items-center justify-between text-sm text-ink-300 transition hover:text-accent-400"
        >
          <span>{{ switchLink.label }}</span>
          <span
            v-if="switchLink.badge"
            class="rounded bg-accent-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-400"
          >
            {{ switchLink.badge }}
          </span>
        </RouterLink>
        <button class="text-sm text-ink-300 transition hover:text-accent-400" @click="logout">
          {{ t("common.signOut") }}
        </button>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header class="border-b border-ink-700 bg-ink-900 md:hidden">
        <div class="flex items-center justify-between px-4 py-3">
          <div class="flex items-center gap-2">
            <LogoMark class="h-5 w-5 text-accent-500" />
            <span class="text-sm font-semibold">EpicWing</span>
          </div>
          <button class="text-sm text-ink-300" @click="logout">{{ t("common.signOut") }}</button>
        </div>
        <nav class="flex gap-4 overflow-x-auto px-4 pb-3 text-sm">
          <RouterLink
            v-for="item in mobileLinks"
            :key="item.to"
            :to="item.to"
            class="whitespace-nowrap text-ink-300"
            exact-active-class="!text-accent-400"
          >
            {{ item.label }}
          </RouterLink>
        </nav>
      </header>

      <main class="min-w-0 flex-1">
        <div class="mx-auto w-full max-w-6xl px-6 py-10">
          <div class="mb-8 flex items-end justify-between gap-4">
            <div>
              <h1 class="text-3xl font-semibold tracking-tight">{{ title }}</h1>
              <p v-if="subtitle" class="mt-1 text-sm text-ink-400">{{ subtitle }}</p>
            </div>
            <slot name="actions" />
          </div>
          <slot />
        </div>
      </main>
    </div>
  </div>
</template>
