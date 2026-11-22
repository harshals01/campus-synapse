import { useState } from "react";
import client, { apiError, setToken } from "../api/client";

export default function LoginPage({ onAuthenticated }) {
  const [collegeId, setCollegeId] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const { data } = await client.post("/auth/login", {
        college_id: collegeId.trim().toLowerCase(),
        password,
      });
      setToken(data.access_token);
      await onAuthenticated();
    } catch (err) {
      setError(apiError(err, "Invalid credentials."));
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1 0-3.12 3 3 0 0 1 0-4.88 2.5 2.5 0 0 1 0-3.12A2.5 2.5 0 0 1 9.5 2z" />
            <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 0-3.12 3 3 0 0 0 0-4.88 2.5 2.5 0 0 0 0-3.12A2.5 2.5 0 0 0 14.5 2z" />
          </svg>
          <h1>Campus Synapse</h1>
        </div>
        <p className="login-subtitle">
          Sign in with your college ID to ask questions about college documents.
        </p>

        <label className="login-label" htmlFor="login-college-id">College ID</label>
        <input
          id="login-college-id"
          className="login-input"
          type="email"
          autoComplete="username"
          placeholder="name@bitmesra.ac.in"
          value={collegeId}
          onChange={(e) => setCollegeId(e.target.value)}
          required
        />

        <label className="login-label" htmlFor="login-password">Password</label>
        <input
          id="login-password"
          className="login-input"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        {error && <p className="upload-status error">{error}</p>}

        <button className="btn-primary login-submit" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="login-footnote">
          Accounts are issued by the college. There is no public sign-up.
        </p>
      </form>
    </div>
  );
}
