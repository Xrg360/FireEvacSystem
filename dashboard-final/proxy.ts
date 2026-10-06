// Optimistic auth gate: send visitors without a session cookie to /login.
// Real authorization happens in the Flask API on every request.
import { NextResponse, type NextRequest } from "next/server";

export function proxy(req: NextRequest) {
  const hasSession = req.cookies.has("fe_refresh") || req.cookies.has("fe_access");
  if (!hasSession) {
    const url = new URL("/login", req.url);
    if (req.nextUrl.pathname !== "/") url.searchParams.set("next", req.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!login|signage|bff|session|_next|favicon.ico|icon.svg).*)"],
};
