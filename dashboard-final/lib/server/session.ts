import "server-only";

import { cookies } from "next/headers";

// Server-side URL of the Flask API (Docker: http://api:5000). Browsers use NEXT_PUBLIC_API_URL.
export const API_URL = process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:5000";

export const ACCESS_COOKIE = "fe_access";
export const REFRESH_COOKIE = "fe_refresh";

const secure = process.env.COOKIE_SECURE === "1";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

export async function setSession(tokens: TokenPair) {
  const jar = await cookies();
  jar.set(ACCESS_COOKIE, tokens.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: Math.max(60, tokens.expires_in - 30),
  });
  jar.set(REFRESH_COOKIE, tokens.refresh_token, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
}

export async function clearSession() {
  const jar = await cookies();
  jar.delete(ACCESS_COOKIE);
  jar.delete(REFRESH_COOKIE);
}

/** Current access token, refreshing it with the refresh cookie when it has expired. */
export async function getAccessToken(forceRefresh = false): Promise<string | null> {
  const jar = await cookies();
  const access = jar.get(ACCESS_COOKIE)?.value;
  if (access && !forceRefresh) return access;
  const refresh = jar.get(REFRESH_COOKIE)?.value;
  if (!refresh) return null;
  const res = await fetch(`${API_URL}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
    cache: "no-store",
  });
  if (!res.ok) {
    await clearSession();
    return null;
  }
  const tokens = (await res.json()) as TokenPair;
  await setSession(tokens);
  return tokens.access_token;
}
