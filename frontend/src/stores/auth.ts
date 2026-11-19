import { reactive, readonly } from "vue";

import { api, setCsrfToken } from "../api/client";

export interface User {
  id: string;
  email: string;
  display_name?: string | null;
  is_admin: boolean;
}

interface AuthResponse {
  user: User;
  csrf_token: string;
}

interface TwoFactorChallenge {
  two_factor_required: true;
  challenge: string;
}

const state = reactive<{ user: User | null; ready: boolean; expired: boolean }>({
  user: null,
  ready: false,
  expired: false,
});

function apply(data: AuthResponse): void {
  state.user = data.user;
  state.expired = false;
  setCsrfToken(data.csrf_token);
}

export const auth = {
  state: readonly(state),

  // Checks once at the start if a valid session still exists.
  async init(): Promise<void> {
    if (state.ready) {
      return;
    }
    try {
      apply(await api<AuthResponse>("/auth/me"));
    } catch {
      state.user = null;
    } finally {
      state.ready = true;
    }
  },

  // Returns a challenge token when the account needs a second factor, otherwise null.
  async login(email: string, password: string): Promise<string | null> {
    const data = await api<AuthResponse | TwoFactorChallenge>("/auth/login", {
      method: "POST",
      body: { email, password },
    });
    if ("two_factor_required" in data) {
      return data.challenge;
    }
    apply(data);
    return null;
  },

  async loginSecondFactor(challenge: string, code: string): Promise<void> {
    apply(
      await api<AuthResponse>("/auth/login/2fa", { method: "POST", body: { challenge, code } }),
    );
  },

  async setName(displayName: string): Promise<User> {
    const user = await api<User>("/auth/me/name", { method: "PUT", body: { display_name: displayName } });
    state.user = user;
    return user;
  },

  // The backend no longer accepts the session (timed out or signed out elsewhere).
  expire(): void {
    if (!state.user) {
      return;
    }
    state.user = null;
    state.expired = true;
    setCsrfToken("");
  },

  async logout(): Promise<void> {
    try {
      await api<void>("/auth/logout", { method: "POST" });
    } finally {
      state.user = null;
      setCsrfToken("");
    }
  },
};
