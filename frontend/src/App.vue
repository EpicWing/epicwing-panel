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

// Der Balken erscheint erst nach 120 ms, damit schnelle Wechsel nicht flackern.
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
