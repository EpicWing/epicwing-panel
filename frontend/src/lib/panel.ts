import { reactive } from "vue";

import { api } from "../api/client";

const DEFAULT_NAME = "EpicWing";

export const panelState = reactive({ name: DEFAULT_NAME, loaded: false });

export function applyPanelName(name: string): void {
  panelState.name = name;
  document.title = name;
}

// The name is public, a failed request keeps the default.
export async function loadPanel(): Promise<void> {
  if (panelState.loaded) return;
  try {
    const data = await api<{ name: string }>("/panel");
    applyPanelName(data.name);
    panelState.loaded = true;
  } catch {
    // The next page load tries again.
  }
}
