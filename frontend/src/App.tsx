import { FormEvent, ReactNode, useEffect, useState } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate, useSearchParams } from "react-router-dom";
import { apiRequest, Appearance, AuthResponse, DEFAULT_APPEARANCE, setUnauthorizedHandler, User, UserTheme } from "./lib/api";
import Landing from "./Landing";
import { Workspace } from "./workspace/Workspace";
import { AdminView } from "./admin/AdminView";

type AuthState = {
  token: string | null;
  user: User | null;
};

function AppRoutes() {
  const [auth, setAuth] = useState<AuthState>({ token: null, user: null });
  const [loading, setLoading] = useState(true);
  // Platform-wide look, chosen in the admin console: which theme the auth pages and the
  // workspace use. Loaded before the first screen so nobody sees one theme flash into
  // another.
  const [appearance, setAppearance] = useState<Appearance>(DEFAULT_APPEARANCE);
  const [appearanceLoading, setAppearanceLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    apiRequest<Appearance>("/api/appearance")
      .then((a) => { if (!cancelled) setAppearance({ ...DEFAULT_APPEARANCE, ...a }); })
      .catch(() => undefined)
      .finally(() => { if (!cancelled) setAppearanceLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Restore the session from the httpOnly refresh-token cookie on load, so a reload
  // (or returning days later) keeps you signed in without a token in localStorage.
  useEffect(() => {
    let cancelled = false;
    apiRequest<AuthResponse>("/api/auth/refresh", { method: "POST" })
      .then((res) => { if (!cancelled) setAuth({ token: res.accessToken, user: res.user }); })
      .catch(() => { if (!cancelled) setAuth({ token: null, user: null }); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Slide the session while the app is open: refresh the short access token on a timer
  // and whenever the tab regains focus, so it never silently expires mid-use.
  useEffect(() => {
    if (!auth.token) return;
    async function slide() {
      try {
        const res = await apiRequest<AuthResponse>("/api/auth/refresh", { method: "POST" });
        setAuth({ token: res.accessToken, user: res.user });
      } catch {
        setAuth({ token: null, user: null });
      }
    }
    const id = window.setInterval(slide, 20 * 60 * 1000);
    function onVisible() { if (document.visibilityState === "visible") slide(); }
    document.addEventListener("visibilitychange", onVisible);
    return () => { window.clearInterval(id); document.removeEventListener("visibilitychange", onVisible); };
  }, [auth.token]);

  // A 401 from any non-auth call means the session is gone (expired/revoked), drop it so
  // the routes redirect to /login instead of leaving the user clicking into silent failures.
  useEffect(() => {
    setUnauthorizedHandler(() => setAuth({ token: null, user: null }));
    return () => setUnauthorizedHandler(null);
  }, []);

  function handleAuth(payload: AuthResponse) {
    setAuth({ token: payload.accessToken, user: payload.user });
  }

  async function logout() {
    try { await apiRequest("/api/auth/logout", { method: "POST" }); } catch { /* ignore */ }
    setAuth({ token: null, user: null });
  }

  async function refreshUser() {
    try {
      const res = await apiRequest<AuthResponse>("/api/auth/refresh", { method: "POST" });
      setAuth({ token: res.accessToken, user: res.user });
    } catch {
      /* keep current state */
    }
  }

  if (loading || appearanceLoading) {
    return <div className="center-screen">Loading your workspace...</div>;
  }

  const ui: UserTheme = appearance.userTheme;

  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route
        path="/login"
        element={auth.token ? <Navigate to="/app" replace /> : <AuthPage mode="login" ui={ui} onAuth={handleAuth} />}
      />
      <Route
        path="/register"
        element={auth.token ? <Navigate to="/app" replace /> : <AuthPage mode="register" ui={ui} onAuth={handleAuth} />}
      />
      <Route path="/forgot-password" element={<ForgotPasswordPage ui={ui} />} />
      <Route path="/reset-password" element={<ResetPasswordPage ui={ui} />} />
      <Route path="/verify-email" element={<VerifyEmailPage ui={ui} />} />
      <Route
        path="/admin"
        element={
          !auth.token ? (
            <Navigate to="/login" replace />
          ) : auth.user && auth.user.isAdmin ? (
            <AdminView token={auth.token} user={auth.user} appearance={appearance} onAppearanceChanged={setAppearance} onLogout={logout} />
          ) : (
            <Navigate to="/app" replace />
          )
        }
      />
      <Route
        path="/app"
        element={
          !auth.token ? (
            <Navigate to="/login" replace />
          ) : auth.user && !auth.user.emailVerified ? (
            <VerifyEmailGate user={auth.user} token={auth.token} ui={ui} onRefresh={refreshUser} onLogout={logout} />
          ) : (
            <Workspace
              token={auth.token}
              user={auth.user}
              ui={ui}
              selfHosted={Boolean(appearance.selfHosted)}
              onLogout={logout}
              onUserUpdated={(user) => setAuth((current) => ({ ...current, user }))}
            />
          )
        }
      />
    </Routes>
  );
}

function AuthPage({
  mode,
  ui,
  onAuth
}: {
  mode: "login" | "register";
  ui: UserTheme;
  onAuth: (payload: AuthResponse) => void;
}) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const isRegister = mode === "register";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      const payload = await apiRequest<AuthResponse>(
        isRegister ? "/api/auth/register" : "/api/auth/login",
        {
          method: "POST",
          body: isRegister ? { name, email, password } : { email, password }
        }
      );
      onAuth(payload);
      navigate("/app");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFrame ui={ui} label={isRegister ? "register" : "login"} onSubmit={submit}>
          <h1>{isRegister ? "Create your account" : "Welcome back"}</h1>
          <p>{isRegister ? "Spin up your team's knowledge base for agents." : "Sign in to your knowledge base."}</p>
          {isRegister && (
            <label>Name
              <input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" />
            </label>
          )}
          <label>Email
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" />
          </label>
          <label>Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={isRegister ? "new-password" : "current-password"} />
          </label>
          {!isRegister && (
            <div style={{ textAlign: "right", margin: "-8px 0 14px" }}>
              <Link to="/forgot-password" className="au-link" style={{ display: "inline", marginTop: 0, fontSize: 12 }}>Forgot password?</Link>
            </div>
          )}
          {error && <div className="au-error">{error}</div>}
          <button className="au-btn" disabled={loading}>
            {loading ? "..." : isRegister ? "Create account" : "Log in"}
          </button>
          <Link to={isRegister ? "/login" : "/register"} className="au-link">
            {isRegister ? "Already have an account? login" : "Need an account? register"}
          </Link>
    </AuthFrame>
  );
}

function ForgotPasswordPage({ ui }: { ui: UserTheme }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await apiRequest("/api/auth/forgot-password", { method: "POST", body: { email } });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFrame ui={ui} label="reset" onSubmit={submit}>
          <h1>Reset your password</h1>
          {sent ? (
            <>
              <p>If an account exists for <b>{email}</b>, we've sent a reset link. It expires in 1 hour.</p>
              <Link to="/login" className="au-link">Back to login</Link>
            </>
          ) : (
            <>
              <p>Enter your email and we'll send you a link to set a new password.</p>
              <label>Email
                <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
              </label>
              {error && <div className="au-error">{error}</div>}
              <button className="au-btn" disabled={loading || !email}>{loading ? "..." : "Send reset link"}</button>
              <Link to="/login" className="au-link">Back to login</Link>
            </>
          )}
    </AuthFrame>
  );
}

function ResetPasswordPage({ ui }: { ui: UserTheme }) {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password.length < 8) { setError("Password must be at least 8 characters."); return; }
    if (password !== confirm) { setError("Passwords don't match."); return; }
    setLoading(true);
    setError("");
    try {
      await apiRequest("/api/auth/reset-password", { method: "POST", body: { token, newPassword: password } });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset your password");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthFrame ui={ui} label="reset" onSubmit={submit}>
          <h1>Set a new password</h1>
          {!token ? (
            <>
              <p>This reset link is missing its token. Request a new one.</p>
              <Link to="/forgot-password" className="au-link">Request a reset link</Link>
            </>
          ) : done ? (
            <>
              <p>Your password has been reset. You can now log in with it.</p>
              <Link to="/login" className="au-btn" style={{ display: "block", textAlign: "center", textDecoration: "none", marginTop: 8 }}>Log in</Link>
            </>
          ) : (
            <>
              <p>Choose a new password for your account.</p>
              <label>New password
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" />
              </label>
              <label>Confirm password
                <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
              </label>
              {error && <div className="au-error">{error}</div>}
              <button className="au-btn" disabled={loading || !password}>{loading ? "..." : "Reset password"}</button>
              <Link to="/login" className="au-link">Back to login</Link>
            </>
          )}
    </AuthFrame>
  );
}

function VerifyEmailGate({ user, token, ui, onRefresh, onLogout }: {
  user: User;
  token: string;
  ui: UserTheme;
  onRefresh: () => void;
  onLogout: () => void;
}) {
  const [resent, setResent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function resend() {
    setBusy(true);
    setError("");
    try {
      await apiRequest("/api/auth/resend-verification", { method: "POST", token });
      setResent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not resend");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame ui={ui} label="verify">
          <h1>Verify your email</h1>
          <p>We sent a verification link to <b>{user.email}</b>. Click it to activate your account, then continue.</p>
          {resent && <p className="au-ok">Sent, check your inbox (and spam).</p>}
          {error && <div className="au-error">{error}</div>}
          <button className="au-btn" onClick={onRefresh}>I've verified, continue</button>
          <button type="button" className="au-ghost" disabled={busy} onClick={resend}>{busy ? "..." : "Resend verification email"}</button>
          <button type="button" className="au-link" onClick={onLogout} style={{ background: "none", border: 0, cursor: "pointer", width: "100%" }}>Log out</button>
    </AuthFrame>
  );
}

function VerifyEmailPage({ ui }: { ui: UserTheme }) {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setState("error");
      setMessage("This verification link is missing its token.");
      return;
    }
    apiRequest("/api/auth/verify-email", { method: "POST", body: { token } })
      .then(() => setState("ok"))
      .catch((err) => {
        setState("error");
        setMessage(err instanceof Error ? err.message : "Verification failed");
      });
  }, [token]);

  return (
    <AuthFrame ui={ui} label="verify">
          <h1>Email verification</h1>
          {state === "working" && <p>Verifying…</p>}
          {state === "ok" && (
            <>
              <p>Your email is verified. 🎉 You can start using Cognivio.</p>
              <button className="au-btn" onClick={() => window.location.assign("/app")}>Continue</button>
            </>
          )}
          {state === "error" && (
            <>
              <div className="au-error">{message}</div>
              <Link to="/login" className="au-link">Back to login</Link>
            </>
          )}
    </AuthFrame>
  );
}

// One chrome for every auth page, drawn in whichever theme the admin console picked.
// Terminal: a dark window with traffic lights and a monospace prompt. Editorial: the
// white page, heavy headline and black buttons of the "Read. Write. Know." landing.
function AuthFrame({ ui, label, onSubmit, children }: {
  ui: UserTheme;
  label: string;
  onSubmit?: (event: FormEvent) => void;
  children: ReactNode;
}) {
  const Card = onSubmit ? "form" : "div";
  return (
    <main className={`au au-${ui}`}>
      <style>{authCss}</style>
      <Link to="/" className="au-brand">{ui === "terminal" ? <>cognivio<span className="cur" /></> : "Cognivio"}</Link>
      <Card className="au-card" onSubmit={onSubmit}>
        {ui === "terminal" ? (
          <div className="au-bar">
            <i style={{ background: "#ff5f56" }} /><i style={{ background: "#ffbd2e" }} /><i style={{ background: "#27c93f" }} />
            <span className="au-bar-label">{label}</span>
          </div>
        ) : (
          <div className="au-label">{label}</div>
        )}
        <div className="au-body">{children}</div>
      </Card>
    </main>
  );
}

const authCss = `
.au{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:22px;padding:24px;position:relative}
.au *{box-sizing:border-box}
.au-link{display:block;text-align:center;text-decoration:none}

.au-terminal{background:#0a0e12;color:#cdd6e0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.au-terminal .au-brand{color:#3ddc84;font-weight:600;font-size:16px;text-decoration:none}
.au-terminal .au-brand .cur{display:inline-block;width:8px;height:16px;background:#3ddc84;margin-left:3px;vertical-align:-2px;animation:a1blink 1s steps(1) infinite}
@keyframes a1blink{50%{opacity:0}}
.au-terminal .au-card{width:100%;max-width:380px;border:1px solid #1c2530;border-radius:10px;overflow:hidden;background:#0d1217;box-shadow:0 24px 70px -34px rgba(0,0,0,.85)}
.au-terminal .au-bar{display:flex;align-items:center;gap:7px;padding:11px 14px;background:#121922;border-bottom:1px solid #1c2530}
.au-terminal .au-bar i{width:11px;height:11px;border-radius:50%;display:block}
.au-terminal .au-bar-label{margin-left:8px;color:#6b7c90;font-size:12px}
.au-terminal .au-body{padding:26px 22px}
.au-terminal .au-body h1{font-size:20px;margin:0 0 4px;color:#eef2f6;font-weight:600}
.au-terminal .au-body p{margin:0 0 22px;color:#7d8da0;font-size:13px;line-height:1.5}
.au-terminal .au-body label{display:block;font-size:12px;color:#8b9bb0;margin-bottom:14px}
.au-terminal .au-body input{display:block;width:100%;margin-top:6px;background:#0a0e12;border:1px solid #1c2530;border-radius:6px;padding:10px 12px;color:#eef2f6;font:inherit;font-size:14px;outline:none}
.au-terminal .au-body input:focus{border-color:#3ddc84}
.au-terminal .au-btn{width:100%;background:#3ddc84;color:#06140c;border:0;border-radius:6px;padding:12px;font:inherit;font-weight:600;font-size:14px;cursor:pointer;margin-top:4px}
.au-terminal .au-btn:hover{background:#54e896}
.au-terminal .au-btn:disabled{opacity:.55;cursor:default}
.au-terminal .au-ghost{width:100%;background:transparent;color:#cdd6e0;border:1px solid #2b3744;border-radius:6px;padding:11px;font:inherit;font-weight:600;font-size:14px;cursor:pointer}
.au-terminal .au-ghost:hover{border-color:#3ddc84;color:#3ddc84}
.au-terminal .au-ghost:disabled{opacity:.55;cursor:default}
.au-terminal .au-error{background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.4);color:#fca5a5;padding:9px 12px;border-radius:6px;font-size:13px;margin-bottom:14px}
.au-terminal .au-ok{color:#3ddc84;font-size:13px;margin:-8px 0 14px}
.au-terminal .au-link{margin-top:18px;color:#7d8da0;font-size:13px}
.au-terminal .au-link:hover{color:#3ddc84}

.au-editorial{background:#fff;color:#111;font-family:-apple-system,"Helvetica Neue",Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased}
.au-editorial .au-brand{position:absolute;top:22px;left:24px;color:#111;font-weight:700;font-size:19px;letter-spacing:-.04em;text-decoration:none}
.au-editorial .au-card{width:100%;max-width:420px}
.au-editorial .au-label{font-size:13px;letter-spacing:.12em;text-transform:uppercase;opacity:.55;font-weight:600;margin:0 0 14px}
.au-editorial .au-body h1{font-size:clamp(34px,5vw,46px);font-weight:700;letter-spacing:-.045em;line-height:1;margin:0 0 12px;color:#111}
.au-editorial .au-body p{margin:0 0 26px;color:#555;font-size:17px;line-height:1.4}
.au-editorial .au-body label{display:block;font-size:13px;font-weight:600;letter-spacing:.04em;color:#111;margin-bottom:16px}
.au-editorial .au-body input{display:block;width:100%;margin-top:6px;background:#fff;border:1.5px solid #111;border-radius:4px;padding:12px 14px;color:#111;font:inherit;font-size:16px;outline:none}
.au-editorial .au-body input:focus{box-shadow:0 0 0 3px rgba(0,0,0,.12)}
.au-editorial .au-btn{width:100%;background:#111;color:#fff;border:1.5px solid #111;border-radius:4px;padding:13px;font:inherit;font-weight:600;font-size:17px;cursor:pointer;margin-top:4px}
.au-editorial .au-btn:hover{background:#333;border-color:#333}
.au-editorial .au-btn:disabled{opacity:.5;cursor:default}
.au-editorial .au-ghost{width:100%;background:#fff;color:#111;border:1.5px solid #111;border-radius:4px;padding:12px;font:inherit;font-weight:600;font-size:17px;cursor:pointer}
.au-editorial .au-ghost:hover{background:#f3efe4}
.au-editorial .au-ghost:disabled{opacity:.5;cursor:default}
.au-editorial .au-error{background:#fdecec;border:1px solid #f3b4b4;color:#b91c1c;padding:10px 12px;border-radius:4px;font-size:14px;margin-bottom:14px}
.au-editorial .au-ok{color:#1d7a46;font-size:14px;margin:-8px 0 14px}
.au-editorial .au-link{margin-top:20px;color:#555;font-size:15px;text-decoration:underline}
.au-editorial .au-link:hover{color:#111}
`;

export function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
