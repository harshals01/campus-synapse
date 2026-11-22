import { Navigate } from "react-router-dom";
import { getToken } from "../api/client";

/**
 * Gate for a dashboard route.
 *
 * This is convenience only — it keeps the wrong screen from rendering. Every API
 * route enforces its own permissions server-side, so a user who edits
 * localStorage gains nothing but a broken page.
 */
export default function ProtectedRoute({ user, allowedRoles, children }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  if (!user) return null; // profile still loading; App renders the splash
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to={`/${user.role}`} replace />;
  }
  return children;
}
