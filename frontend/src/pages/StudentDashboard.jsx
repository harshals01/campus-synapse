import { useState } from "react";
import ChatPanel from "../components/ChatPanel";
import DashboardShell from "../components/DashboardShell";
import DocumentSidebar from "../components/DocumentSidebar";
import UploadModal from "../components/UploadModal";
import useDocuments from "../hooks/useDocuments";

export default function StudentDashboard({ currentUser, isDark, onToggleTheme }) {
  const { documents, loading, refresh } = useDocuments();
  const [selectedDocumentId, setSelectedDocumentId] = useState(null);
  const [showUpload, setShowUpload] = useState(false);

  return (
    <>
      <DashboardShell
        currentUser={currentUser}
        isDark={isDark}
        onToggleTheme={onToggleTheme}
        sidebar={
          <DocumentSidebar
            documents={documents}
            currentUser={currentUser}
            selectedDocumentId={selectedDocumentId}
            onSelectDocument={setSelectedDocumentId}
            onUploadClick={() => setShowUpload(true)}
            onRefresh={refresh}
            loading={loading}
          />
        }
      >
        <ChatPanel
          documents={documents}
          selectedDocumentId={selectedDocumentId}
          onSelectDocument={setSelectedDocumentId}
        />
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
