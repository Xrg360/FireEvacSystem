import { NextResponse, type NextRequest } from "next/server";

import { API_URL, setSession, type TokenPair } from "@/lib/server/session";

export async function POST(req: NextRequest) {
  const { email, password } = (await req.json().catch(() => ({}))) as { email?: string; password?: string };
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ message: "Cannot reach the evacuation server" }, { status: 502 });
  }
  const data = (await res.json().catch(() => ({}))) as TokenPair & { message?: string; user?: { role: string; status: string } };
  if (!res.ok) return NextResponse.json({ message: data.message ?? "Login failed" }, { status: res.status });
  if (data.user && !["society_admin", "rescuer", "surveyor"].includes(data.user.role)) {
    return NextResponse.json({ message: "The dashboard is for society admins and rescuers. Residents use the mobile app." }, { status: 403 });
  }
  await setSession(data);
  return NextResponse.json({ user: data.user });
}
