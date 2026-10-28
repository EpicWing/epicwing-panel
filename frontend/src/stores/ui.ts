import { reactive, readonly } from "vue";

export type UiMode = "simple" | "advanced";

const KEY = "epicwing.ui_mode";

function load(): UiMode {
  try {
    return localStorage.getItem(KEY) === "advanced" ? "advanced" : "simple";
  } catch {
    return "simple";
  }
}

const state = reactive<{ mode: UiMode }>({ mode: load() });

// Wird vorerst nur im Browser gespeichert, später kann das ans Konto gehen.
export const ui = {
  state: readonly(state),

  setMode(mode: UiMode): void {
    state.mode = mode;
    try {
      localStorage.setItem(KEY, mode);
    } catch {
      // Storage is not available, the mode only lasts for this session.
    }
  },
};
