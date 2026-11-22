import { useCallback, useEffect, useRef, useState } from "react";
import client from "../api/client";

/**
 * Loads GET /documents and keeps it fresh.
 *
 * Indexing happens in a background task server-side, so a freshly uploaded
 * document arrives as `processing`. While any document is in that state the list
 * is re-polled every few seconds, and polling stops once everything settles.
 */
export default function useDocuments() {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const timer = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const { data } = await client.get("/documents");
      setDocuments(Array.isArray(data) ? data : []);
    } catch {
      // 401 is handled by the interceptor; anything else leaves the list as-is.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const pending = documents.some((d) => d.active_version_status === "processing");
    clearTimeout(timer.current);
    if (pending) {
      timer.current = setTimeout(refresh, 3000);
    }
    return () => clearTimeout(timer.current);
  }, [documents, refresh]);

  return { documents, loading, refresh };
}
