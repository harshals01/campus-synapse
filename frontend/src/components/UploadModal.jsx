import { useRef, useState } from "react";
import client, { apiError } from "../api/client";

const BRANCHES = ["CSE", "ECE", "EEE", "AI", "BCA", "MCA", "BAM"];
const SEMESTERS = [1, 2, 3, 4, 5, 6, 7, 8];
const SECTIONS = ["A", "B"];

/**
 * Audience options the server will actually accept, by role.
 * The server re-derives all of this from the uploader's role, so these options
 * only keep the form honest — they are not the security boundary.
 */
function audienceOptionsFor(role) {
  if (role === "admin") {
    return [
      { value: "personal", label: "Private to me" },
      { value: "everyone", label: "Everyone in the college" },
      { value: "students", label: "All students" },
      { value: "teachers", label: "All teachers" },
      { value: "class", label: "A specific class" },
    ];
  }
  if (role === "teacher") {
    return [
      { value: "personal", label: "Private to me" },
      { value: "class", label: "A class in my branch" },
    ];
  }
  return [{ value: "personal", label: "Private to me" }];
}

export default function UploadModal({ currentUser, onClose, onUploaded }) {
  const [file, setFile] = useState(null);
  const [audienceType, setAudienceType] = useState("personal");
  const [branch, setBranch] = useState(currentUser.branch || "CSE");
  const [semester, setSemester] = useState("");
  const [section, setSection] = useState("");
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState(null);
  const fileInputRef = useRef(null);

  const options = audienceOptionsFor(currentUser.role);
  const isClass = audienceType === "class";
  const canChooseBranch = currentUser.role === "admin";

  const submit = async () => {
    if (!file || uploading) return;
    if (file.type && file.type !== "application/pdf") {
      setStatus({ type: "error", message: "Only PDF files are accepted." });
      return;
    }

    setUploading(true);
    setStatus(null);

    const form = new FormData();
    form.append("file", file);
    form.append("audience_type", audienceType);
    if (isClass) {
      form.append("audience_branch", canChooseBranch ? branch : currentUser.branch || "");
      if (semester) form.append("audience_semester", semester);
      if (section) form.append("audience_section", section);
    }

    try {
      const { data } = await client.post("/ingest", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setStatus({
        type: "success",
        message: `"${data.display_name}" uploaded. Indexing has started — the status will turn Ready shortly.`,
      });
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await onUploaded();
      setTimeout(onClose, 1600);
    } catch (err) {
      setStatus({ type: "error", message: apiError(err, "Upload failed.") });
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Upload a PDF</h2>
          <button className="icon-btn" onClick={onClose} title="Close" aria-label="Close">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <p className="upload-hint">
          The document is split into chunks and indexed so Synapse can answer questions
          about it and cite the page. Scanned PDFs without a text layer are not supported.
        </p>

        <input
          id="pdf-file-input"
          ref={fileInputRef}
          type="file"
          accept="application/pdf"
          className="file-input"
          onChange={(e) => {
            setFile(e.target.files[0] || null);
            setStatus(null);
          }}
        />

        <label className="login-label" htmlFor="audience-select">Who can read it</label>
        <select
          id="audience-select"
          className="login-input"
          value={audienceType}
          onChange={(e) => setAudienceType(e.target.value)}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        {isClass && (
          <div className="audience-grid">
            <div>
              <label className="login-label" htmlFor="audience-branch">Branch</label>
              {canChooseBranch ? (
                <select
                  id="audience-branch"
                  className="login-input"
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                >
                  {BRANCHES.map((b) => <option key={b} value={b}>{b}</option>)}
                </select>
              ) : (
                <input
                  id="audience-branch"
                  className="login-input"
                  value={currentUser.branch || "—"}
                  readOnly
                  title="Teachers can only share within their own branch"
                />
              )}
            </div>
            <div>
              <label className="login-label" htmlFor="audience-semester">Semester</label>
              <select
                id="audience-semester"
                className="login-input"
                value={semester}
                onChange={(e) => setSemester(e.target.value)}
              >
                <option value="">All semesters</option>
                {SEMESTERS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="login-label" htmlFor="audience-section">Section</label>
              <select
                id="audience-section"
                className="login-input"
                value={section}
                onChange={(e) => setSection(e.target.value)}
              >
                <option value="">All sections</option>
                {SECTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
          </div>
        )}

        {file && !status && (
          <p className="upload-hint">Selected: <strong>{file.name}</strong></p>
        )}
        {status && <p className={`upload-status ${status.type}`}>{status.message}</p>}

        <div className="upload-controls">
          <button className="btn-secondary" onClick={onClose} disabled={uploading}>Cancel</button>
          <button
            id="upload-submit-btn"
            className="btn-primary"
            onClick={submit}
            disabled={!file || uploading}
          >
            {uploading ? "Uploading…" : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}
