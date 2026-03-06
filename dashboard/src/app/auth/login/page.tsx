"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";

export default function LoginPage() {
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    setLoading(false);
    if (!res.ok) {
      setError("Invalid credentials");
      return;
    }
    router.replace("/");
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm rounded-xl border border-line bg-[color:var(--panel)] p-6 shadow-[0_8px_30px_rgba(2,6,23,0.35)]">
        <h1 className="mb-1 text-lg font-semibold text-ink">Operator Login</h1>
        <p className="mb-4 text-xs uppercase tracking-[0.15em] text-ink-faint">Market Intelligence Platform</p>
        <div className="mb-3">
          <label className="mb-1 block text-xs text-ink-faint">Username</label>
          <Input value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="mb-4">
          <label className="mb-1 block text-xs text-ink-faint">Password</label>
          <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error ? <p className="mb-3 text-sm text-red-600">{error}</p> : null}
        <Button type="submit" loading={loading} className="w-full">Sign In</Button>
      </form>
    </div>
  );
}
