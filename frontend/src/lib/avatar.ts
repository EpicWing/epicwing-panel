import { reactive } from "vue";

// Goes up after upload/delete, so all avatars are loaded again.
export const avatarState = reactive({ version: 0 });

export function bumpAvatars(): void {
  avatarState.version = Date.now();
}
