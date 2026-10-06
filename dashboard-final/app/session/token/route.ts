// Short-lived access token for the Socket.IO handshake (kept in memory only by the client).
import { NextResponse } from "next/server";

import { getAccessToken } from "@/lib/server/session";

export const dynamic = "force-dynamic";

export async function GET() {
  const token = await getAccessToken();
  if (!token) return NextResponse.json({ message: "Not signed in" }, { status: 401 });
  return NextResponse.json({ token }, { headers: { "cache-control": "no-store" } });
}
