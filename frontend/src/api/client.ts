const BASE = "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* no json body */
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return undefined as T;
  return res.json();
}

function qs(params?: Record<string, unknown>): string {
  if (!params) return "";
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
    return fetch(`${BASE}${path}${qs(params)}`).then(handle<T>);
  },
  post<T>(path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
    return fetch(`${BASE}${path}${qs(params)}`, {
      method: "POST",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }).then(handle<T>);
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return fetch(`${BASE}${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(handle<T>);
  },
  delete<T>(path: string): Promise<T> {
    return fetch(`${BASE}${path}`, { method: "DELETE" }).then(handle<T>);
  },
  postForm<T>(path: string, form: FormData): Promise<T> {
    return fetch(`${BASE}${path}`, { method: "POST", body: form }).then(handle<T>);
  },
  fileUrl(path: string, params?: Record<string, unknown>): string {
    return `${BASE}${path}${qs(params)}`;
  },
};
