import { ref } from "vue";

export type ThemeChoice = "light" | "dark" | "system";

const KEY = "epicwing-theme";
// Duration of the fade, matches .theme-fade in style.css
const FADE_MS = 300;

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    // Speicher gesperrt (z. B. privater Modus): Standard nehmen
  }
  // Default stays dark so nothing changes for existing users
  return "dark";
}

const choice = ref<ThemeChoice>(readChoice());
// In tests (without matchMedia) there is no system query
const query = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: light)") : null;

function resolve(): "light" | "dark" {
  if (choice.value === "system") return query?.matches ? "light" : "dark";
  return choice.value;
}

function apply(animate: boolean) {
  const root = document.documentElement;
  const theme = resolve();
  if (animate) {
    // Set the class only briefly so the fade happens only when switching
    root.classList.add("theme-fade");
    window.setTimeout(() => root.classList.remove("theme-fade"), FADE_MS);
  }
  root.dataset.theme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "light" ? "#dcdce2" : "#09090a");
  document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", theme);
}

// Call once on startup: syncs the theme and follows the system when "System" is selected
export function initTheme() {
  apply(false);
  query?.addEventListener("change", () => {
    if (choice.value === "system") apply(true);
  });
}

export function useTheme() {
  function setTheme(value: ThemeChoice) {
    choice.value = value;
    try {
      localStorage.setItem(KEY, value);
    } catch {
      // Saving is not possible: the choice only lasts until the next reload
    }
    apply(true);
  }
  return { choice, setTheme };
}
