import { forwardRef, useImperativeHandle, useState } from "react";
import client, { API_BASE, apiError } from "../api/client";

/**
 * Collapsible "Sources Cited" panel below an assistant message.
 *
 * Extracted from the original App.jsx with its markup and classes unchanged. Two
 * things are new: citations now carry `display_name` and `document_id` instead of
 * `source_file`, and each card can open the original PDF at the cited page.
 */
const CitationsAccordion = forwardRef(function CitationsAccordion({ citations }, ref) {
  const [open, setOpen] = useState(false);
  const [highlightedIds, setHighlightedIds] = useState([]);
  const [opening, setOpening] = useState(null);
  const [error, setError] = useState(null);

  useImperativeHandle(ref, () => ({
    openAndHighlight(ids) {
      setOpen(true);
      setHighlightedIds(ids);
      // Delay scroll to allow accordion to render
      setTimeout(() => {
        const el = document.getElementById(`citation-${ids[0]}`);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 120);
    },
  }));

  if (!citations || citations.length === 0) return null;

  /**
   * Mint a short-lived preview token and open the PDF at the cited page.
   * The token grants nothing by itself: /files/{token} re-checks the account and
   * the access policy on every request.
   */
  const viewPage = async (citation) => {
    setOpening(citation.id);
    setError(null);
    try {
      const { data } = await client.post(
        `/documents/${citation.document_id}/preview-link`,
        null,
        { params: citation.page_number ? { page: citation.page_number } : {} },
      );
      window.open(
        `${API_BASE}/files/${data.token}${data.page_fragment}`,
        "_blank",
        "noopener,noreferrer",
      );
    } catch (err) {
      setError(apiError(err, "Could not open this document."));
    } finally {
      setOpening(null);
    }
  };

  return (
    <div className="citations-accordion">
      <button
        className="citations-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
        Sources Cited ({citations.length})
        <svg
          className={`citations-chevron ${open ? "open" : ""}`}
          width="12" height="12" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {open && (
        <div className="citations-list">
          {error && <p className="upload-status error">{error}</p>}
          {citations.map((c) => (
            <div
              key={c.id}
              className={`citation-card ${highlightedIds?.includes(c.id) ? "highlighted" : ""} ${c.unavailable ? "unavailable" : ""}`}
              id={`citation-${c.id}`}
            >
              <div className="citation-card-header">
                <span className="citation-index">[{c.id}]</span>
                <span className="citation-filename">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 4 }}>
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                  </svg>
                  {c.display_name || "unknown"}
                </span>
                {c.page_number && (
                  <span className="citation-page">Page {c.page_number}</span>
                )}
                {typeof c.score === "number" && (
                  <span className="citation-score" title="Relevance score">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" style={{ marginRight: 3 }}>
                      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                    </svg>
                    {(c.score * 1000).toFixed(1)}
                  </span>
                )}
                {!c.unavailable && c.document_id && (
                  <button
                    className="citation-view-btn"
                    onClick={() => viewPage(c)}
                    disabled={opening === c.id}
                    title={c.page_number ? `Open page ${c.page_number}` : "Open document"}
                  >
                    {opening === c.id ? "Opening…" : "View page"}
                  </button>
                )}
              </div>
              <p className="citation-snippet">&ldquo;{c.snippet}&rdquo;</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

export default CitationsAccordion;
