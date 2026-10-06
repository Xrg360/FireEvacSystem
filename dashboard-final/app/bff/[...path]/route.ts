// Backend-for-frontend proxy: /bff/<path> -> Flask /api/<path> with the JWT from the httpOnly
// cookie. Retries once with a refreshed token on 401.
import { NextResponse, type NextRequest } from "next/server";

import { API_URL, getAccessToken } from "@/lib/server/session";

export const dynamic = "force-dynamic";

const PASS_HEADERS = ["content-type", "content-disposition"];

async function forward(req: NextRequest, path: string[], body: ArrayBuffer | undefined, token: string | null) {
  const url = new URL(`${API_URL}/api/${path.map(encodeURIComponent).join("/")}`);
  req.nextUrl.searchParams.forEach((v, k) => url.searchParams.append(k, v));
  const headers: Record<string, string> = {};
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  if (token) headers.authorization = `Bearer ${token}`;
  return fetch(url, { method: req.method, headers, body, cache: "no-store", redirect: "manual" });
}

async function handler(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const body = req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer();
  let token = await getAccessToken();
  let res: Response;
  try {
    res = await forward(req, path, body, token);
    if (res.status === 401 && token) {
      token = await getAccessToken(true);
      if (token) res = await forward(req, path, body, token);
    }
  } catch {
    return NextResponse.json({ message: "Evacuation server unreachable" }, { status: 502 });
  }
  const out = new NextResponse(res.status === 204 ? null : await res.arrayBuffer(), { status: res.status });
  for (const h of PASS_HEADERS) {
    const v = res.headers.get(h);
    if (v) out.headers.set(h, v);
  }
  out.headers.set("cache-control", "no-store");
  return out;
}

export { handler as GET, handler as POST, handler as PUT, handler as PATCH, handler as DELETE };
