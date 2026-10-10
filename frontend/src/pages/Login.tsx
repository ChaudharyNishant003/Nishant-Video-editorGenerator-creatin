import { useState, type FormEvent } from "react";
import { api, ApiError } from "../api";

export function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/login", { body: { password } });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "लॉग-इन नहीं हो सका।");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>AI YT Studio</h1>
        <p className="muted">जारी रखने के लिए पासवर्ड डालें।</p>
        <label htmlFor="pw">पासवर्ड</label>
        <input id="pw" className="input" type="password" autoComplete="current-password" autoFocus
               value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <div className="msg error" role="alert">{error}</div>}
        <button className="btn primary full" disabled={busy || !password}>{busy ? "जाँच हो रही है…" : "लॉग-इन"}</button>
      </form>
    </div>
  );
}
