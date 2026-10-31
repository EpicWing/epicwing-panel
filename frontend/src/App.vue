<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { useRouter } from "vue-router";

const router = useRouter();
const busy = ref(false);
let timer: number | undefined;

function stop() {
  window.clearTimeout(timer);
  busy.value = false;
}

// The bar only shows after 120 ms, so quick changes do not flicker.
const offStart = router.beforeEach(() => {
  window.clearTimeout(timer);
  timer = window.setTimeout(() => (busy.value = true), 120);
});
const offEnd = router.afterEach(stop);
const offError = router.onError(stop);

onBeforeUnmount(() => {
  offStart();
  offEnd();
  offError();
  stop();
});
</script>

<template>
  <div class="route-bar" :class="{ 'route-bar--on': busy }" aria-hidden="true" />
  <RouterView />
</template>
