import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getJSON, postJSON, setLoggedOutHandler } from "./api.js";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }) {
  const [state, set] = useState({ user: null, checked: false });

  const refresh = useCallback(() =>
    getJSON("auth/me")
      .then((user) => set({ user, checked: true }))
      .catch(() => set({ user: null, checked: true })), []);

  useEffect(() => {
    setLoggedOutHandler(() => set({ user: null, checked: true }));
    refresh();
  }, [refresh]);

  const login = async (username, password) => {
    await getJSON("auth/csrf");
    const user = await postJSON("auth/login", { username, password });
    set({ user, checked: true });
  };
  const logout = async () => {
    try { await postJSON("auth/logout"); } finally { set({ user: null, checked: true }); }
  };

  return <AuthCtx.Provider value={{ ...state, login, logout }}>{children}</AuthCtx.Provider>;
}

export function LoginPage() {
  const { login } = useAuth();
  const [form, setForm] = useState({ username: "", password: "" });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try { await login(form.username.trim(), form.password); }
    catch (ex) { setErr(ex.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <form className="login" onSubmit={submit}>
        <div className="brand">
          <span className="mark">Rx</span>
          <div>
            <div className="title">Infusion Drug Markup Audit</div>
            <div className="sub">Sign in to continue</div>
          </div>
        </div>
        <label>Username
          <input autoFocus autoComplete="username" value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </label>
        <label>Password
          <input type="password" autoComplete="current-password" value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </label>
        {err && <div className="note error">{err}</div>}
        <button className="button" disabled={busy || !form.username || !form.password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <div className="muted">Accounts are created by the admin. Ask the admin for access.</div>
      </form>
    </div>
  );
}
