import { Navigate, useLocation } from "react-router-dom";

import { clearToken, hasValidToken } from "@/lib/auth";

const ProtectedRoute = ({ children }) => {
  const location = useLocation();

  if (!hasValidToken()) {
    clearToken();
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return children;
};

export default ProtectedRoute;
