import { clearSession } from "../api/client";

const ROLE_LABEL = { student: "Student", teacher: "Teacher", admin: "Admin" };

/**
 * Shared chrome for all three dashboards: header, sidebar slot, main slot.
 *
 * Not in the original plan's file list, but the three role dashboards would
 * otherwise repeat this header and layout verbatim three times.
 */
export default function DashboardShell({
  currentUser,
  isDark,
  onToggleTheme,
  tabs,
  activeTab,
  onTabChange,
  sidebar,
  children,
}) {
  const profileBits = [currentUser.branch, currentUser.semester && `sem ${currentUser.semester}`, currentUser.section]
    .filter(Boolean)
    .join(" · ");

  const signOut = () => {
    clearSession();
    window.location.replace("/login");
  };

  return (
    <div className="app-container dashboard">
      <div className="header">
        <div className="brand">
          <svg className="brand-icon" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96-.44 2.5 2.5 0 0 1 0-3.12 3 3 0 0 1 0-4.88 2.5 2.5 0 0 1 0-3.12A2.5 2.5 0 0 1 9.5 2z" />
            <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96-.44 2.5 2.5 0 0 0 0-3.12 3 3 0 0 0 0-4.88 2.5 2.5 0 0 0 0-3.12A2.5 2.5 0 0 0 14.5 2z" />
          </svg>
          <h1>Campus Synapse</h1>
          <span className="role-chip">{ROLE_LABEL[currentUser.role] || currentUser.role}</span>
        </div>

        {tabs?.length > 1 && (
          <nav className="tab-bar">
            {tabs.map((t) => (
              <button
                key={t.key}
                className={`tab-btn ${activeTab === t.key ? "active" : ""}`}
                onClick={() => onTabChange(t.key)}
              >
                {t.label}
              </button>
            ))}
          </nav>
        )}

        <div className="header-actions">
          <div className="user-chip" title={currentUser.college_id}>
            <span className="user-name">{currentUser.name}</span>
            {profileBits && <span className="user-meta">{profileBits}</span>}
          </div>

          <button
            className="theme-toggle"
            onClick={onToggleTheme}
            title={isDark ? "Switch to light mode" : "Switch to dark mode"}
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
          >
            {isDark ? (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="5" />
                <line x1="12" y1="1" x2="12" y2="3" />
                <line x1="12" y1="21" x2="12" y2="23" />
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                <line x1="1" y1="12" x2="3" y2="12" />
                <line x1="21" y1="12" x2="23" y2="12" />
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
              </svg>
            ) : (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            )}
          </button>

          <button className="header-btn" onClick={signOut} title="Sign out">
            <svg className="btn-icon" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
              <polyline points="16 17 21 12 16 7" />
              <line x1="21" y1="12" x2="9" y2="12" />
            </svg>
            <span>Sign out</span>
          </button>
        </div>
      </div>

      <div className={`dashboard-body ${sidebar ? "with-sidebar" : ""}`}>
        {sidebar}
        <main className="dashboard-main">{children}</main>
      </div>
    </div>
  );
}
