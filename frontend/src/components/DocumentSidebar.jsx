import { useState } from "react";
import client, { apiError } from "../api/client";

const STATUS_LABEL = {
  ready: "Ready",
  processing: "Indexing",
  failed: "Failed",
};

function StatusBadge({ status }) {
  const key = status || "processing";
  return (
    <span className={`doc-status doc-status-${key}`}>
      {key === "processing" ? <span className="doc-spinner" /> : <span className="doc-dot" />}
      {STATUS_LABEL[key] || key}
    </span>
  );
}

function audienceLabel(doc) {
  if (doc.category === "personal") return "Private to you";
  switch (doc.audience_type) {
    case "everyone": return "Everyone";
    case "students": return "All students";
    case "teachers": return "All teachers";
    case "class": {
      const bits = [doc.audience_branch];
      if (doc.audience_semester) bits.push(`sem ${doc.audience_semester}`);
      if (doc.audience_section) bits.push(`sec ${doc.audience_section}`);
      return bits.filter(Boolean).join(" · ");
    }
    default: return "Shared";
  }
}

export default function DocumentSidebar({
  documents,
  currentUser,
  selectedDocumentId,
  onSelectDocument,
  onUploadClick,
  onRefresh,
  loading,
}) {
  const [busyId, setBusyId] = useState(null);
  const [error, setError] = useState(null);

  const remove = async (doc) => {
    if (!window.confirm(`Delete "${doc.display_name}"? This also removes its indexed text.`)) return;
    setBusyId(doc.id);
    setError(null);
    try {
      await client.delete(`/documents/${doc.id}`);
      if (selectedDocumentId === doc.id) onSelectDocument(null);
      await onRefresh();
    } catch (err) {
      setError(apiError(err, "Could not delete that document."));
    } finally {
      setBusyId(null);
    }
  };

  // A personal document is only ever visible to its owner, so these are "yours".
  // Anything shared sits in the other group even when you published it yourself.
  const mine = documents.filter((d) => d.category === "personal");
  const shared = documents.filter((d) => d.category !== "personal");

  const renderDoc = (doc) => {
    const isOwn = doc.owner_id === currentUser.id;
    return (
      <li
        key={doc.id}
        className={`doc-item ${selectedDocumentId === doc.id ? "selected" : ""}`}
      >
        <button
          className="doc-item-main"
          onClick={() =>
            onSelectDocument(selectedDocumentId === doc.id ? null : doc.id)
          }
          disabled={doc.active_version_status !== "ready"}
          title={
            doc.active_version_status === "ready"
              ? "Search only this document"
              : "Not searchable yet"
          }
        >
          <span className="doc-name">{doc.display_name}</span>
          <span className="doc-meta">
            <StatusBadge status={doc.active_version_status} />
            <span className="doc-audience">{audienceLabel(doc)}</span>
            {doc.chunk_count ? <span className="doc-chunks">{doc.chunk_count} chunks</span> : null}
          </span>
        </button>
        {isOwn && (
          <button
            className="doc-delete"
            onClick={() => remove(doc)}
            disabled={busyId === doc.id}
            title="Delete this document"
            aria-label={`Delete ${doc.display_name}`}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        )}
      </li>
    );
  };

  return (
    <aside className="doc-sidebar">
      <div className="doc-sidebar-head">
        <h2 className="section-label">Documents</h2>
        <div className="doc-sidebar-actions">
          <button className="icon-btn" onClick={onRefresh} disabled={loading} title="Refresh list">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="23 4 23 10 17 10" />
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
            </svg>
          </button>
          <button className="btn-secondary doc-upload-btn" onClick={onUploadClick}>Upload</button>
        </div>
      </div>

      {error && <p className="upload-status error">{error}</p>}

      {documents.length === 0 && !loading && (
        <p className="doc-empty">
          Nothing here yet. Upload a PDF, or wait for the college to publish one for you.
        </p>
      )}

      {shared.length > 0 && (
        <>
          <h3 className="doc-group-label">Shared with you</h3>
          <ul className="doc-list">{shared.map(renderDoc)}</ul>
        </>
      )}

      {mine.length > 0 && (
        <>
          <h3 className="doc-group-label">Your uploads</h3>
          <ul className="doc-list">{mine.map(renderDoc)}</ul>
        </>
      )}
    </aside>
  );
}
