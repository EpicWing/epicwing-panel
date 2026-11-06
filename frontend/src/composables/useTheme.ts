import { ref } from "vue";

export type ThemeChoice = "light" | "dark" | "system";

const KEY = "epicwing-theme";
// Dauer der Überblendung, passend zu .theme-fade in style.css
const FADE_MS = 300;

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    // Speicher gesperrt (z. B. privater Modus): Standard nehmen
  }
  // Standard bleibt dunkel, damit sich für bestehende Nutzer nichts ändert
  return "dark";
}

const choice = ref<ThemeChoice>(readChoice());
// In Tests (ohne matchMedia) gibt es keine Systemabfrage
const query = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-color-scheme: light)") : null;

function resolve(): "light" | "dark" {
  if (choice.value === "system") return query?.matches ? "light" : "dark";
  return choice.value;
}

function apply(animate: boolean) {
  const root = document.documentElement;
  const theme = resolve();
  if (animate) {
    // Klasse nur kurz setzen, damit nur beim Umschalten überblendet wird
    root.classList.add("theme-fade");
    window.setTimeout(() => root.classList.remove("theme-fade"), FADE_MS);
  }
  root.dataset.theme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "light" ? "#dcdce2" : "#09090a");
  document.querySelector('meta[name="color-scheme"]')?.setAttribute("content", theme);
}

// Einmal beim Start aufrufen: gleicht das Theme ab und folgt dem System, wenn "System" gewählt ist
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
      // Speichern nicht möglich: Auswahl gilt nur bis zum Neuladen
    }
    apply(true);
  }
  return { choice, setTheme };
}
