import { reactive } from "vue";

// Wird nach Upload/Löschen erhöht, damit alle Avatare neu geladen werden.
export const avatarState = reactive({ version: 0 });

export function bumpAvatars(): void {
  avatarState.version = Date.now();
}
