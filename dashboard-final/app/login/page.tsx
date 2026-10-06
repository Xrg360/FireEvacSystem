"use client";

import { Flame, Loader2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Field, Input } from "@/components/ui/primitives";

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/session/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message ?? "Login failed");
      router.replace(next.startsWith("/") ? next : "/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader className="gap-3 p-6 pb-2">
        <div className="flex items-center gap-2">
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Flame className="size-5" />
          </span>
          <div>
            <CardTitle className="text-base">Fire Evacuation Command</CardTitle>
            <CardDescription>For rescuers and society admins</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-6 pt-4">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="Email">
            <Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </Field>
          <Field label="Password">
            <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          {error && (
            <p role="alert" className="rounded-md bg-fire/10 px-3 py-2 text-sm text-fire">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy} size="lg">
            {busy && <Loader2 className="animate-spin" />} Sign in
          </Button>
          <p className="text-center text-[11px] text-muted-foreground">Residents use the mobile app. Not a certified life-safety system.</p>
        </form>
      </CardContent>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-gradient-to-br from-background via-background to-primary/10 p-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
