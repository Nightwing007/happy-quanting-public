"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSignup } from "@/lib/queries";

function SignupForm() {
  const router = useRouter();
  const next = useSearchParams().get("next");
  // Only same-site paths: "//evil.com" and "http://..." must not be followed.
  const dest = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
  const signup = useSignup();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const mismatch = confirm !== "" && confirm !== password;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) return;
    signup.mutate(
      { username: username.trim(), password, display_name: displayName.trim() || null },
      { onSuccess: () => router.replace(dest) },
    );
  }

  return (
    <Card className="mx-auto mt-8 w-full max-w-sm">
      <CardHeader>
        <CardTitle>Create an account</CardTitle>
        <CardDescription>
          Usernames are 3 to 30 characters: a-z, 0-9 and _. Passwords need at least 8 characters.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="username">Username</Label>
            <Input id="username" autoComplete="username" autoCapitalize="none" required value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="display-name">Display name (optional)</Label>
            <Input id="display-name" autoComplete="name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="confirm">Confirm password</Label>
            <Input id="confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </div>
          {(mismatch || signup.isError) && (
            <p role="alert" className="text-sm text-destructive">
              {mismatch ? "The two passwords don't match." : signup.error?.message}
            </p>
          )}
          <Button type="submit" disabled={signup.isPending || mismatch}>
            {signup.isPending ? "Creating account..." : "Sign up"}
          </Button>
          <p className="text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link href={next ? `/login?next=${encodeURIComponent(next)}` : "/login"} className="underline">
              Log in
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}

export default function SignupPage() {
  // useSearchParams needs a Suspense boundary or `next build` fails.
  return (
    <Suspense fallback={<p className="text-sm text-muted-foreground">Loading...</p>}>
      <SignupForm />
    </Suspense>
  );
}
