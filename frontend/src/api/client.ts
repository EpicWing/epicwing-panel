export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Das CSRF-Token liegt nur im Speicher und wird bei Login und /auth/me gesetzt.
let csrfToken = "";

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = {};
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (method !== "GET") {
    headers["X-CSRF-Token"] = csrfToken;
  }

  const response = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (!response.ok) {
    let detail = `Fehler ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        detail = data.detail;
      } else if (Array.isArray(data.detail) && typeof data.detail[0]?.msg === "string") {
        // Validierungsfehler von FastAPI: erste Meldung ohne technisches Präfix.
        detail = data.detail[0].msg.replace(/^Value error, /, "");
      }
    } catch {
      // Antwort ohne JSON-Body, die allgemeine Meldung bleibt.
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
