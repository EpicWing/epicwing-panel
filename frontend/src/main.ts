import { createApp } from "vue";

import App from "./App.vue";
import i18n from "./i18n";
import { initTheme } from "./composables/useTheme";
import router from "./router";
import "./style.css";

// Sync the theme and follow the system when "System" is selected
initTheme();

createApp(App).use(router).use(i18n).mount("#app");
