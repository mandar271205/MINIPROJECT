import { Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "sonner";

import ProtectedRoute from "@/components/ProtectedRoute";
import AcademicManagementPage from "@/pages/academic";
import AttendanceReportPage from "@/pages/attendance/[id]";
import ClassDetailPage from "@/pages/classes/[id]";
import DashboardPage from "@/pages/dashboard";
import IndexPage from "@/pages/index";
import LoginPage from "@/pages/login";
import RegisterPage from "@/pages/register";
import StudentProfilePage from "@/pages/student/profile";

const App = () => {
  return (
    <div>
      <Toaster position="bottom-right" richColors />
      <Routes>
        <Route path="/" element={<IndexPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />

        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <DashboardPage />
            </ProtectedRoute>
          }
        />

        <Route
          path="/classes/:id"
          element={
            <ProtectedRoute>
              <ClassDetailPage />
            </ProtectedRoute>
          }
        />

        <Route
          path="/attendance/:id"
          element={
            <ProtectedRoute>
              <AttendanceReportPage />
            </ProtectedRoute>
          }
        />

        <Route
          path="/academic"
          element={
            <ProtectedRoute roles={["hod"]}>
              <AcademicManagementPage />
            </ProtectedRoute>
          }
        />

        <Route
          path="/student/profile"
          element={
            <ProtectedRoute roles={["student"]}>
              <StudentProfilePage />
            </ProtectedRoute>
          }
        />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
};

export default App;