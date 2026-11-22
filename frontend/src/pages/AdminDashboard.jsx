import { useCallback, useEffect, useState } from "react";
import client, { apiError } from "../api/client";
import ChatPanel from "../components/ChatPanel";
import DashboardShell from "../components/DashboardShell";
import DocumentSidebar from "../components/DocumentSidebar";
import UploadModal from "../components/UploadModal";
import useDocuments from "../hooks/useDocuments";

const BRANCHES = ["CSE", "ECE", "EEE", "AI", "BCA", "MCA", "BAM"];
const SECTIONS = ["A", "B"];

const TABS = [
  { key: "chat", label: "Chat & Documents" },
  { key: "accounts", label: "Accounts" },
  { key: "questions", label: "Questions" },
];

/* ── Accounts tab ──────────────────────────────────────────────────────────── */

function AccountsTab() {
  const [users, setUsers] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    college_id: "", name: "", password: "", role: "student",
    branch: "CSE", semester: "", section: "",
  });

  const load = useCallback(async () => {
    try {
      const { data } = await client.get("/admin/users");
      setUsers(data);
    } catch (err) {
      setError(apiError(err, "Could not load accounts."));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const create = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    const payload = {
      college_id: form.college_id.trim().toLowerCase(),
      name: form.name.trim(),
      password: form.password,
      role: form.role,
      branch: form.role === "admin" ? null : form.branch || null,
      semester: form.role === "student" && form.semester ? Number(form.semester) : null,
      section: form.role === "student" && form.section ? form.section : null,
    };
    try {
      await client.post("/admin/users", payload);
      setNotice(`Created ${payload.college_id}.`);
      setForm({ ...form, college_id: "", name: "", password: "" });
      await load();
    } catch (err) {
      setError(apiError(err, "Could not create that account."));
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (user) => {
    setError(null);
    try {
      await client.patch(`/admin/users/${user.id}`, { active: !user.active });
      await load();
    } catch (err) {
      setError(apiError(err, "Could not update that account."));
    }
  };

  return (
    <div className="admin-pane">
      <section className="admin-block">
        <h2 className="section-label">Create an account</h2>
        <form className="account-form" onSubmit={create}>
          <input
            className="login-input" type="email" required
            placeholder="name@bitmesra.ac.in" value={form.college_id}
            onChange={(e) => setForm({ ...form, college_id: e.target.value })}
          />
          <input
            className="login-input" required minLength={2}
            placeholder="Full name" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            className="login-input" type="password" required minLength={6}
            placeholder="Initial password" value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
          <select
            className="login-input" value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
          >
            <option value="student">Student</option>
            <option value="teacher">Teacher</option>
            <option value="admin">Admin</option>
          </select>
          {form.role !== "admin" && (
            <select
              className="login-input" value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
            >
              {BRANCHES.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          )}
          {form.role === "student" && (
            <>
              <select
                className="login-input" value={form.semester}
                onChange={(e) => setForm({ ...form, semester: e.target.value })}
              >
                <option value="">Semester…</option>
                {[1, 2, 3, 4, 5, 6, 7, 8].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <select
                className="login-input" value={form.section}
                onChange={(e) => setForm({ ...form, section: e.target.value })}
              >
                <option value="">Section…</option>
                {SECTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </>
          )}
          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? "Creating…" : "Create"}
          </button>
        </form>
        {error && <p className="upload-status error">{error}</p>}
        {notice && <p className="upload-status success">{notice}</p>}
      </section>

      <section className="admin-block">
        <h2 className="section-label">Accounts ({users.length})</h2>
        <div className="table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>College ID</th><th>Name</th><th>Role</th>
                <th>Branch</th><th>Sem</th><th>Sec</th><th>Status</th><th />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className={u.active ? "" : "row-inactive"}>
                  <td>{u.college_id}</td>
                  <td>{u.name}</td>
                  <td>{u.role}</td>
                  <td>{u.branch || "—"}</td>
                  <td>{u.semester ?? "—"}</td>
                  <td>{u.section || "—"}</td>
                  <td>
                    <span className={`doc-status doc-status-${u.active ? "ready" : "failed"}`}>
                      <span className="doc-dot" />
                      {u.active ? "Active" : "Disabled"}
                    </span>
                  </td>
                  <td>
                    <button className="btn-secondary small" onClick={() => toggleActive(u)}>
                      {u.active ? "Deactivate" : "Reactivate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="upload-hint">
          Deactivating takes effect on the account&apos;s very next request: the token
          carries only a user ID, and the server re-reads the account each time.
        </p>
      </section>
    </div>
  );
}

/* ── Questions tab ─────────────────────────────────────────────────────────── */

function QuestionsTab() {
  const [rows, setRows] = useState([]);
  const [unansweredOnly, setUnansweredOnly] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setError(null);
      try {
        const { data } = await client.get("/admin/questions", {
          params: unansweredOnly ? { answered: false } : {},
        });
        if (!cancelled) setRows(data);
      } catch (err) {
        if (!cancelled) setError(apiError(err, "Could not load the question log."));
      }
    })();
    return () => { cancelled = true; };
  }, [unansweredOnly]);

  return (
    <div className="admin-pane">
      <section className="admin-block">
        <div className="questions-head">
          <h2 className="section-label">
            {unansweredOnly ? "Questions with no answer" : "All questions"} ({rows.length})
          </h2>
          <label className="toggle-label">
            <input
              type="checkbox"
              checked={unansweredOnly}
              onChange={(e) => setUnansweredOnly(e.target.checked)}
            />
            Unanswered only
          </label>
        </div>
        <p className="upload-hint">
          Questions the documents could not answer show what information is missing,
          or published to the wrong audience.
        </p>
        {error && <p className="upload-status error">{error}</p>}
        <div className="table-wrap">
          <table className="admin-table">
            <thead>
              <tr><th>Asked</th><th>Question</th><th>Outcome</th><th>Top similarity</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="nowrap">{new Date(r.created_at).toLocaleString()}</td>
                  <td>{r.question}</td>
                  <td>
                    <span className={`doc-status doc-status-${r.answered ? "ready" : "failed"}`}>
                      <span className="doc-dot" />
                      {r.answered ? "Answered" : "No answer"}
                    </span>
                  </td>
                  <td>{r.top_similarity == null ? "—" : r.top_similarity.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && !error && (
            <p className="doc-empty">Nothing logged yet.</p>
          )}
        </div>
      </section>
    </div>
  );
}

/* ── Dashboard ─────────────────────────────────────────────────────────────── */

export default function AdminDashboard({ currentUser, isDark, onToggleTheme }) {
  const { documents, loading, refresh } = useDocuments();
  const [selectedDocumentId, setSelectedDocumentId] = useState(null);
  const [showUpload, setShowUpload] = useState(false);
  const [tab, setTab] = useState("chat");

  return (
    <>
      <DashboardShell
        currentUser={currentUser}
        isDark={isDark}
        onToggleTheme={onToggleTheme}
        tabs={TABS}
        activeTab={tab}
        onTabChange={setTab}
        sidebar={
          tab === "chat" ? (
            <DocumentSidebar
              documents={documents}
              currentUser={currentUser}
              selectedDocumentId={selectedDocumentId}
              onSelectDocument={setSelectedDocumentId}
              onUploadClick={() => setShowUpload(true)}
              onRefresh={refresh}
              loading={loading}
            />
          ) : null
        }
      >
        {tab === "chat" && (
          <ChatPanel
            documents={documents}
            selectedDocumentId={selectedDocumentId}
            onSelectDocument={setSelectedDocumentId}
          />
        )}
        {tab === "accounts" && <AccountsTab />}
        {tab === "questions" && <QuestionsTab />}
      </DashboardShell>

      {showUpload && (
        <UploadModal
          currentUser={currentUser}
          onClose={() => setShowUpload(false)}
          onUploaded={refresh}
        />
      )}
    </>
  );
}
