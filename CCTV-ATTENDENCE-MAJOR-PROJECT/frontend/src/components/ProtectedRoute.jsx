import { Navigate, useLocation } from "react-router-dom";

import { clearToken, getTokenUser, hasValidToken } from "@/lib/auth";

// `roles`, when given, restricts the route to those roles. This is a
// convenience redirect only - the backend is the actual authority and
// enforces permissions independently on every request (frontend route
// hiding is never trusted as authorization by itself).
const ProtectedRoute = ({ children, roles }) => {
  const location = useLocation();

  if (!hasValidToken()) {
    clearToken();
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  if (roles && roles.length > 0) {
    const user = getTokenUser();
    if (!user || !roles.includes(user.role)) {
      return <Navigate to="/dashboard" replace />;
    }
  }

  return children;
};

export default ProtectedRoute;
