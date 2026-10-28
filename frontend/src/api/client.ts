export class ApiError extends Error {
  status: number;
  // Stable error code from the backend (for example PORT_IN_USE), if there is one.
  code?: string;
  // Raw text from the node. The backend only sends it to admins.
  technical?: string;

  constructor(status: number, message: string, code?: string, technical?: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.technical = technical;
  }
}

// The CSRF token only lives in memory and is set on login and /auth/me.
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
    let detail = `Error ${response.status}`;
    let code: string | undefined;
    let technical: string | undefined;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        detail = data.detail;
      } else if (Array.isArray(data.detail) && typeof data.detail[0]?.msg === "string") {
        // FastAPI validation error: first message without the technical prefix.
        detail = data.detail[0].msg.replace(/^Value error, /, "");
      }
      if (typeof data.code === "string") code = data.code;
      if (typeof data.technical === "string") technical = data.technical;
    } catch {
      // Response without a JSON body, the generic message stays.
    }
    throw new ApiError(response.status, detail, code, technical);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// Raw upload (no JSON), used for profile pictures.
export async function apiUpload(path: string, file: Blob): Promise<void> {
  const response = await fetch(`/api${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/octet-stream", "X-CSRF-Token": csrfToken },
    credentials: "same-origin",
    body: file,
  });
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") {
        detail = data.detail;
      }
    } catch {
      // Response without a JSON body, the generic message stays.
    }
    throw new ApiError(response.status, detail);
  }
}
