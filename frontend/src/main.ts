import { createApp } from "vue";

import App from "./App.vue";
import i18n from "./i18n";
import { initTheme } from "./composables/useTheme";
import router from "./router";
import "./style.css";

// Theme abgleichen und dem System folgen, wenn "System" gewählt ist
initTheme();

createApp(App).use(router).use(i18n).mount("#app");
