"use client";
import { useEffect, useState } from "react";

// Secure password gate — only password Nish123456789101119009 unlocks the app.
// Hash is SHA-256 of the password, stored in localStorage so device stays logged in.
// Plain password never touches storage, only its hash.

const CORRECT_HASH = "f7b34c1249bce4c7c64136c97089bcd681a3b6a7fa03e13b8ea3fcf846c1bb57";
const STORAGE_KEY = "nishagent_auth_v1";
const STORAGE_TIME_KEY = "nishagent_auth_time";

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [checking, setChecking] = useState(true);
  const [authed, setAuthed] = useState(false);
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [attempts, setAttempts] = useState(0);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && saved === CORRECT_HASH) {
        setAuthed(true);
      }
    } catch {}
    setChecking(false);
  }, []);

  async function handleLogin(e?: React.FormEvent) {
    e?.preventDefault();
    if (loading) return;
    setError("");
    const trimmed = password.trim();
    if (!trimmed) {
      setError("Please enter the password.");
      return;
    }
    setLoading(true);
    try {
      const hash = await sha256Hex(trimmed);
      if (hash === CORRECT_HASH) {
        try {
          localStorage.setItem(STORAGE_KEY, hash);
          localStorage.setItem(STORAGE_TIME_KEY, String(Date.now()));
        } catch {}
        setAuthed(true);
        setPassword("");
        setAttempts(0);
      } else {
        const next = attempts + 1;
        setAttempts(next);
        if (next >= 5) {
          setError("Too many attempts. Wait a moment and try again.");
          await new Promise((r) => setTimeout(r, 1500));
        } else {
          setError("Incorrect password. Try again broo.");
        }
      }
    } catch {
      setError("Something went wrong. Try again.");
    } finally {
      setLoading(false);
    }
  }

  function handleLogout() {
    try {
      localStorage.removeItem(STORAGE_KEY);
      localStorage.removeItem(STORAGE_TIME_KEY);
    } catch {}
    setAuthed(false);
    setPassword("");
    setError("");
  }

  // Expose logout globally so header buttons can call it without prop drilling
  useEffect(() => {
    (window as any).nishLogout = handleLogout;
    return () => {
      try {
        delete (window as any).nishLogout;
      } catch {}
    };
  }, []);

  if (checking) {
    return (
      <div className="min-h-screen bg-[#09090b] grid place-items-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-10 w-10 rounded-2xl bg-zinc-900 border border-zinc-800 grid place-items-center animate-pulse-subtle">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="text-zinc-500"><path d="M12 1C9.8 1 8 2.8 8 5v3H7c-1.1 0-2 .9-2 2v7c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2v-7c0-1.1-.9-2-2-2h-1V5c0-2.2-1.8-4-4-4zM12 3c1.1 0 2 .9 2 2v3H10V5c0-1.1.9-2 2-2zm5 8v7H7v-7h10z" fill="currentColor" /></svg>
          </div>
          <div className="text-xs text-zinc-600 tracking-wide">Checking secure access…</div>
        </div>
      </div>
    );
  }

  if (!authed) {
    return (
      <div className="min-h-screen bg-[#09090b] relative flex items-center justify-center p-4 overflow-hidden">
        {/* ambient glow */}
        <div className="absolute inset-0 -z-10">
          <div className="absolute inset-0 bg-grid opacity-[0.03]" />
          <div className="absolute -top-32 -left-32 h-[480px] w-[480px] rounded-full bg-violet-600/10 blur-[80px]" />
          <div className="absolute -bottom-32 -right-32 h-[520px] w-[520px] rounded-full bg-cyan-600/10 blur-[90px]" />
          <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-[#09090b]" />
        </div>

        <div className="w-full max-w-[420px]">
          {/* brand */}
          <div className="flex flex-col items-center mb-6">
            <div className="h-12 w-12 rounded-2xl bg-white text-zinc-900 grid place-items-center shadow-large">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none"><path d="M12 1L3 5v6c0 5.5 3.8 10.7 9 12 5.2-1.3 9-6.5 9-12V5L12 1z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/><path d="M9 12l2 2 4-5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </div>
            <h1 className="mt-4 text-[22px] font-semibold tracking-tight">NishAgent</h1>
            <p className="text-sm text-zinc-500 mt-1">Secure access — one password for your device</p>
          </div>

          <div className="rounded-[22px] bg-zinc-900 border border-zinc-800 shadow-large overflow-hidden animate-slideIn">
            <div className="p-6 sm:p-7">
              <div className="flex items-center gap-2 mb-1">
                <span className="h-7 w-7 rounded-xl bg-zinc-800 border border-zinc-700 grid place-items-center">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="text-zinc-400"><path d="M17 11H7c-1.1 0-2 .9-2 2v4c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2v-4c0-1.1-.9-2-2-2z" stroke="currentColor" strokeWidth="1.5"/><path d="M8 11V8c0-2.2 1.8-4 4-4s4 1.8 4 4v3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
                </span>
                <h2 className="text-sm font-semibold tracking-tight">Enter password</h2>
                <span className="ml-auto text-[11px] px-2 py-0.5 rounded-full bg-emerald-950/40 border border-emerald-900/50 text-emerald-300 font-medium">Device-locked</span>
              </div>
              <p className="text-xs leading-relaxed text-zinc-500 mb-5">Only the correct password unlocks the studio. It stays saved on <span className="text-zinc-300">this device</span> — no need to enter again.</p>

              <form onSubmit={handleLogin} className="space-y-4">
                <div>
                  <label className="text-[11px] font-semibold tracking-widest text-zinc-500 uppercase">Password</label>
                  <div className="mt-2 relative group">
                    <input
                      type={show ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••••••••••••••••"
                      className="w-full h-[46px] rounded-xl bg-zinc-950 border border-zinc-800 group-focus-within:border-zinc-700 focus:border-violet-600 outline-none px-4 pr-[88px] text-sm tracking-wide placeholder:text-zinc-600 transition-colors"
                      autoFocus
                      autoComplete="current-password"
                    />
                    <div className="absolute right-1 top-1 bottom-1 flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => setShow((s) => !s)}
                        className="h-full px-3 rounded-lg bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-colors"
                      >
                        {show ? "Hide" : "Show"}
                      </button>
                    </div>
                  </div>
                  <div className="text-[11px] text-zinc-600 mt-2 flex items-center gap-1.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500/70" />
                    Saved securely on this device after first login
                  </div>
                </div>

                {error && (
                  <div className="rounded-xl bg-red-950/30 border border-red-900/50 px-3.5 py-2.5 flex items-start gap-2.5 animate-slideIn">
                    <span className="mt-0.5 h-5 w-5 rounded-full bg-red-950 border border-red-900 grid place-items-center shrink-0">
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" className="text-red-400"><path d="M12 8v6M12 16h.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
                    </span>
                    <p className="text-xs leading-relaxed text-red-300">{error}</p>
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full h-[46px] rounded-xl bg-white hover:bg-zinc-100 text-zinc-900 font-semibold text-sm flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed transition-colors shadow-soft"
                >
                  {loading ? (
                    <>
                      <span className="h-4 w-4 border-2 border-zinc-300 border-t-zinc-900 rounded-full animate-spin" />
                      Checking…
                    </>
                  ) : (
                    <>
                      Unlock
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M5 3L9 7L5 11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    </>
                  )}
                </button>

                <p className="text-center text-[11px] leading-relaxed text-zinc-600">
                  Password is <span className="text-zinc-500 font-medium">Nish123456789101119009</span> — kept hashed (SHA-256) in your browser. No server sees it.
                </p>
              </form>
            </div>

            <div className="px-6 sm:px-7 py-3 bg-zinc-950 border-t border-zinc-800 flex items-center gap-2 text-[11px] text-zinc-600">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" className="text-zinc-500"><path d="M12 22C6.5 22 2 17.5 2 12S6.5 2 12 2s10 4.5 10 10-4.5 10-10 10z" stroke="currentColor" strokeWidth="1.4"/><path d="M12 8v5M12 16h.01" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
              Tip: use your device passcode/biometrics to protect this browser.
            </div>
          </div>

          <p className="text-center text-[11px] text-zinc-700 mt-4">© NishAgent • nishagent.vercel.app</p>
        </div>
      </div>
    );
  }

  return (
    <>
      {children}
      {/* subtle logout — does not interfere with app UI, but always reachable */}
      <button
        onClick={handleLogout}
        title="Lock this device (logout)"
        className="fixed bottom-3 right-3 z-50 hidden sm:flex h-8 px-3 rounded-full bg-zinc-900/80 backdrop-blur border border-zinc-800 text-[11px] font-medium text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 hover:border-zinc-700 transition-colors items-center gap-1.5 shadow-soft"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M16 17l5-5-5-5M21 12H9M13 22H6a2 2 0 01-2-2V4a2 2 0 012-2h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
        Lock
      </button>
    </>
  );
}
