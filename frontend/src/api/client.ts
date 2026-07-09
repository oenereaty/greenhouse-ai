// 배포 시 프론트와 백엔드가 서로 다른 origin에 있을 수 있으므로, 빌드 시점에
// VITE_API_BASE로 절대 URL을 주입한다. 로컬 개발은 미설정 시 "/api"로 남아
// vite.config.ts의 proxy를 그대로 탄다.
const BASE = import.meta.env.VITE_API_BASE ? `${import.meta.env.VITE_API_BASE}/api` : "/api";

// 백엔드가 backend/auth.py::verify_api_key로 보호되어 있을 때(BACKEND_API_KEY
// 설정 시)만 필요 — 미설정 시 빈 문자열이라 헤더를 안 보내도 백엔드가 통과시킨다.
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined;
const authHeaders: Record<string, string> = API_KEY ? { "x-api-key": API_KEY } : {};

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
    return fetch(`${BASE}${path}${qs(params)}`, { headers: authHeaders }).then(handle<T>);
  },
  post<T>(path: string, body?: unknown, params?: Record<string, unknown>): Promise<T> {
    return fetch(`${BASE}${path}${qs(params)}`, {
      method: "POST",
      headers: body !== undefined ? { ...authHeaders, "Content-Type": "application/json" } : authHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }).then(handle<T>);
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return fetch(`${BASE}${path}`, {
      method: "PUT",
      headers: { ...authHeaders, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(handle<T>);
  },
  delete<T>(path: string): Promise<T> {
    return fetch(`${BASE}${path}`, { method: "DELETE", headers: authHeaders }).then(handle<T>);
  },
  postForm<T>(path: string, form: FormData): Promise<T> {
    return fetch(`${BASE}${path}`, { method: "POST", headers: authHeaders, body: form }).then(handle<T>);
  },
  fileUrl(path: string, params?: Record<string, unknown>): string {
    // <a href>로 직접 여는 다운로드 링크라 fetch처럼 x-api-key 헤더를 못 붙인다 —
    // BACKEND_API_KEY가 설정된 환경(로컬 .env에 실수로 켜져도 포함)에서는 쿼리
    // 파라미터로 같은 키를 실어 보낸다(backend/auth.py가 쿼리 파라미터도 허용).
    const withKey = API_KEY ? { ...params, api_key: API_KEY } : params;
    return `${BASE}${path}${qs(withKey)}`;
  },
};
