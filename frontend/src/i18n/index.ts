import { createI18n } from "vue-i18n";

import en from "./en";

// German will be added later as a second language file.
export default createI18n({
  legacy: false,
  locale: "en",
  fallbackLocale: "en",
  messages: { en },
});
