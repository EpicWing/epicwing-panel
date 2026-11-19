import { createApp } from "vue";

import App from "./App.vue";
import { onUnauthorized } from "./api/client";
import { auth } from "./stores/auth";
import i18n from "./i18n";
import { initTheme } from "./composables/useTheme";
import router from "./router";
import "./style.css";

// Theme abgleichen und dem System folgen, wenn "System" gewählt ist
initTheme();

onUnauthorized(() => {
  if (!auth.state.user) {
    return;
  }
  auth.expire();
  const current = router.currentRoute.value;
  if (current.name !== "login") {
    void router.replace({ name: "login", query: { next: current.fullPath } });
  }
});

createApp(App).use(router).use(i18n).mount("#app");
