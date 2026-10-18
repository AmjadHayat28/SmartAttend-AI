import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../hooks/useAuth";
import { ROLE_HOME, type UserRole } from "../../types/auth";
import { Spinner } from "../ui/Feedback";

/** Requires a logged-in user; optionally restricts to specific roles. */
export function ProtectedRoute({ roles }: { roles?: UserRole[] }) {
  const { user, initializing } = useAuth();
  const location = useLocation();

  if (initializing) return <Spinner label="Restoring session…" className="min-h-screen" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/unauthorized" replace />;
  return <Outlet />;
}

/** Login/register pages: bounce already-authenticated users to their dashboard. */
export function GuestRoute() {
  const { user, initializing } = useAuth();
  if (initializing) return <Spinner label="Loading…" className="min-h-screen" />;
  if (user) return <Navigate to={ROLE_HOME[user.role]} replace />;
  return <Outlet />;
}
