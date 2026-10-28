import { reactive, readonly } from "vue";

import { api, setCsrfToken } from "../api/client";

export interface User {
  id: string;
  email: string;
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

const state = reactive<{ user: User | null; ready: boolean }>({
  user: null,
  ready: false,
});

function apply(data: AuthResponse): void {
  state.user = data.user;
  setCsrfToken(data.csrf_token);
}

export const auth = {
  state: readonly(state),

  // Prüft einmalig beim Start, ob noch eine gültige Session besteht.
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

  async logout(): Promise<void> {
    try {
      await api<void>("/auth/logout", { method: "POST" });
    } finally {
      state.user = null;
      setCsrfToken("");
    }
  },
};
