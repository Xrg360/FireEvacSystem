// Browser-side API client. All REST calls go through the Next.js BFF (/bff/*), which attaches
// the JWT from an httpOnly cookie and refreshes it transparently.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
  }
}

type Json = Record<string, unknown> | unknown[];

async function request<T>(method: string, path: string, body?: Json | FormData): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(`/bff${path.startsWith("/") ? path : `/${path}`}`, init);
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth/")) {
    // full reload on purpose: clears all client state when the session is gone
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    throw new ApiError(401, "Session expired");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const message = (data && typeof data === "object" && "message" in data ? String(data.message) : null) ?? res.statusText;
    const detail = data && typeof data === "object" && "detail" in data ? data.detail : undefined;
    throw new ApiError(res.status, message, detail);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: Json | FormData) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: Json) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: Json) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const problems = (err.detail as { problems?: string[] } | undefined)?.problems;
    if (problems?.length) return `${err.message}: ${problems.join("; ")}`;
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong";
}
