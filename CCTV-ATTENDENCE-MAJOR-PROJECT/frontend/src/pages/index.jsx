import { Navigate } from "react-router-dom";

import { hasValidToken } from "@/lib/auth";

const IndexPage = () => {
  if (hasValidToken()) {
    return <Navigate to="/dashboard" replace />;
  }

  return <Navigate to="/login" replace />;
};

export default IndexPage;
