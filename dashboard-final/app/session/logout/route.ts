import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { API_URL, REFRESH_COOKIE, clearSession } from "@/lib/server/session";

export async function POST() {
  const refresh = (await cookies()).get(REFRESH_COOKIE)?.value;
  if (refresh) {
    await fetch(`${API_URL}/api/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    }).catch(() => undefined);
  }
  await clearSession();
  return NextResponse.json({ ok: true });
}
