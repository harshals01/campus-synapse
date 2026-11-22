import { useEffect, useRef, useState } from "react";
import client, { apiError } from "../api/client";
import CitationsAccordion from "./CitationsAccordion";

const STORAGE_KEY = "chat_context";
const generateId = () => crypto.randomUUID();
const getTimestamp = () => new Date().toISOString();

/* ── Message formatting (regex and markup unchanged from the original) ─────── */

const formatBold = (text, keyPrefix = "") => {
  if (!text) return [];
  return text.split("**").map((token, i) =>
    i % 2 === 1 ? <strong key={`${keyPrefix}-b${i}`}>{token}</strong> : token
  );
};

const formatMessage = (text) => {
  if (!text) return "";
  return text.split("**").map((token, i) =>
    i % 2 === 1 ? <strong key={i}>{token}</strong> : token
  );
};

const formatMessageWithCitations = (text, citations = [], onBadgeClick) => {
  if (!text) return "";
  const parts = [];
  const citationRegex = /\[(\d+(?:[,\s]*\d+)*)\]/g;
  let lastIndex = 0;
  let match;

  while ((match = citationRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(...formatBold(text.slice(lastIndex, match.index), `pre-${match.index}`));
    }
    const ids = match[1].split(/[,\s]+/).map(Number).filter(Boolean);
    parts.push(
      <span
        key={`cite-${match.index}`}
        className="citation-badge"
        onClick={() => onBadgeClick && onBadgeClick(ids)}
        title={`View source${ids.length > 1 ? "s" : ""} ${ids.join(", ")}`}
      >
        {ids.map((id) => `[${id}]`).join("")}
      </span>
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(...formatBold(text.slice(lastIndex), `tail-${lastIndex}`));
  }
  return parts.length ? parts : text;
};

const formatTime = (isoString) => {
  if (!isoString) return "";
  try {
    return new Date(isoString).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
};

function MessageItem({ msg, isUser }) {
  const accordionRef = useRef(null);
  const handleBadgeClick = (ids) => accordionRef.current?.openAndHighlight(ids);

  return (
    <div className={`chat-item ${isUser ? "user" : "bot"}`}>
      <div className="chat-tag">{isUser ? "You" : "Synapse"}</div>
      <div className={`chat-bubble ${isUser ? "user" : "bot"} ${msg.abstained ? "abstained" : ""}`}>
        <div className="msg-text">
          {isUser
            ? formatMessage(msg.content)
            : formatMessageWithCitations(msg.content, msg.citations, handleBadgeClick)}
        </div>
        <span className="bubble-timestamp">{formatTime(msg.timestamp)}</span>
      </div>
      {!isUser && msg.citations?.length > 0 && (
        <CitationsAccordion ref={accordionRef} citations={msg.citations} />
      )}
    </div>
  );
}

/* ── Panel ─────────────────────────────────────────────────────────────────── */

export default function ChatPanel({ documents, selectedDocumentId, onSelectDocument }) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [messages, setMessages] = useState(() => {
    try {
      return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}").context || [];
    } catch {
      return [];
    }
  });

  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ context: messages.slice(-50) }));
  }, [messages]);

  // The backend starts a fresh conversation when the document scope changes, so
  // drop the stale id rather than letting it reply about the old scope.
  useEffect(() => {
    setConversationId(null);
  }, [selectedDocumentId]);

  const readyDocuments = documents.filter((d) => d.active_version_status === "ready");

  const send = async () => {
    if (!query.trim() || loading) return;
    setLoading(true);

    const userMessage = { id: generateId(), role: "user", content: query, timestamp: getTimestamp() };
    const history = [...messages, userMessage];
    const placeholder = {
      id: generateId(), role: "assistant", content: "", timestamp: getTimestamp(), citations: [],
    };
    setMessages([...history, placeholder]);
    setQuery("");

    try {
      const { data } = await client.post("/chat", {
        messages: history.map((m) => ({ role: m.role, content: m.content })),
        conversation_id: conversationId,
        document_ids: selectedDocumentId ? [selectedDocumentId] : null,
      });
      setConversationId(data.conversation_id);
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: data.reply,
          citations: data.citations || [],
          abstained: data.abstained,
        };
        return updated;
      });
    } catch (error) {
      const detail = apiError(error, "Unknown error");
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: `Error: ${detail}`,
          abstained: true,
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setConversationId(null);
    sessionStorage.removeItem(STORAGE_KEY);
  };

  return (
    <div className="chat-pane">
      <div className="chat-pane-toolbar">
        <div className="doc-scope-wrapper" title="Choose which document to search">
          <svg className="doc-scope-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          <select
            id="doc-scope-select"
            className="doc-scope-select"
            value={selectedDocumentId || ""}
            onChange={(e) => onSelectDocument(e.target.value || null)}
            aria-label="Document search scope"
          >
            <option value="">All documents available to me</option>
            {readyDocuments.map((d) => (
              <option key={d.id} value={d.id}>{d.display_name}</option>
            ))}
          </select>
        </div>

        <button className="header-btn btn-clear" onClick={clearChat} disabled={!messages.length}>
          <svg className="btn-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
          <span>Clear Chat</span>
        </button>
      </div>

      <div className="chat-container">
        {messages.map((msg) => (
          <MessageItem key={msg.id} msg={msg} isUser={msg.role === "user"} />
        ))}
        <div ref={bottomRef} />
      </div>

      <div className={`input-section ${messages.length === 0 ? "centered" : "bottom"}`}>
        {messages.length === 0 && (
          <div className="hero-container">
            <h2 className="hero-title">What would you like to know?</h2>
            <p className="hero-subtitle">
              Answers come only from documents you have access to, with the page cited.
            </p>
          </div>
        )}
        <div className="input-wrapper">
          <input
            id="chat-input"
            type="text"
            placeholder="Ask about fees, syllabus, timetables…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && query.trim() && !loading) send();
            }}
          />
          <button id="chat-send-btn" onClick={send} disabled={loading || !query.trim()} title="Send message">
            {loading ? (
              <span className="spinner" />
            ) : (
              <svg className="send-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
