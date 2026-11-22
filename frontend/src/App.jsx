import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import client, { clearSession, getToken } from "./api/client";
import ProtectedRoute from "./components/ProtectedRoute";
import AdminDashboard from "./pages/AdminDashboard";
import LoginPage from "./pages/LoginPage";
import StudentDashboard from "./pages/StudentDashboard";
import TeacherDashboard from "./pages/TeacherDashboard";
import "./App.css";

const THEME_KEY = "synapse_theme";

export default function App() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(Boolean(getToken()));

  const [isDark, setIsDark] = useState(() => {
    const saved = localStorage.getItem(THEME_KEY);
    return saved ? saved === "dark" : true;
  });

  useEffect(() => {
    if (isDark) {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = "light";
    }
    localStorage.setItem(THEME_KEY, isDark ? "dark" : "light");
  }, [isDark]);

  /** Load the signed-in user's profile. The role decides which dashboard renders. */
  const loadProfile = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setChecking(false);
      return null;
    }
    try {
      const { data } = await client.get("/auth/me");
      setUser(data);
      return data;
    } catch {
      clearSession();
      setUser(null);
      return null;
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  const onAuthenticated = async () => {
    const profile = await loadProfile();
    if (profile) navigate(`/${profile.role}`, { replace: true });
  };

  if (checking) {
    return (
      <div className="splash">
        <span className="spinner" />
        <p>Signing you in…</p>
      </div>
    );
  }

  const dashboardProps = {
    currentUser: user,
    isDark,
    onToggleTheme: () => setIsDark((v) => !v),
  };

  return (
    <Routes>
      <Route
        path="/login"
        element={
          user ? <Navigate to={`/${user.role}`} replace /> : <LoginPage onAuthenticated={onAuthenticated} />
        }
      />
      <Route
        path="/student"
        element={
          <ProtectedRoute user={user} allowedRoles={["student"]}>
            <StudentDashboard {...dashboardProps} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/teacher"
        element={
          <ProtectedRoute user={user} allowedRoles={["teacher"]}>
            <TeacherDashboard {...dashboardProps} />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <ProtectedRoute user={user} allowedRoles={["admin"]}>
            <AdminDashboard {...dashboardProps} />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to={user ? `/${user.role}` : "/login"} replace />} />
    </Routes>
  );
}
